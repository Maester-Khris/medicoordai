"""Semantic candidate lookup with deadline, circuit breaker, and bulkhead protections.

The semantic search stage embeds user utterances and searches a vector index to find
relevant symptom concepts and anchors. To ensure stability and low latency in production,
three layered protections isolate the application from failure or latency degradation
in the embedding model or vector search:

1. Deadline: A slow embedder must not slow a chat turn. Each lookup enforces a strict
   timeout (deadline_ms). If the embedding/search takes longer than this limit, the
   operation times out immediately and records a breaker failure rather than blocking
   the chat turn.
2. Breaker: Stop calling a failing embedder. If consecutive lookups fail or time out,
   the circuit breaker trips open to shed load immediately without invoking the model,
   allowing the underlying service or ONNX runtime time to recover. After a cooldown
   period, a single probe is admitted to test recovery before reopening normal traffic.
3. Bulkhead: Bounded in-flight work so slow turns cannot pile up. Concurrency is limited
   by a bounded semaphore sized to the executor capacity (threads running plus an equally
   long queue: 2 * threads). Excess requests are rejected immediately with 'queue_full'
   without touching the breaker, and semaphore permits are held until worker futures
   actually terminate, preventing thread pool exhaustion when tasks hang.
"""

from __future__ import annotations

import concurrent.futures
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import threading
import time
from typing import Any, Callable, Sequence

import numpy as np

from graph.semantic.settings import SemanticSettings
from metrics import SEMANTIC_EMBED_DURATION, SEMANTIC_OUTCOMES


@dataclass(frozen=True)
class Candidate:
    concept_id: str
    anchor_id: str
    score: float
    text: str


@dataclass(frozen=True)
class CandidateResult:
    candidates: tuple[Candidate, ...] = ()
    skipped: str | None = None


class Breaker:
    """Thread-safe circuit breaker with closed, open, and half-open states."""

    def __init__(
        self,
        failures: int,
        cooldown_s: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.failures: int = failures
        self.cooldown_s: float = cooldown_s
        self.clock: Callable[[], float] = clock
        self._lock: threading.Lock = threading.Lock()
        self._consecutive_failures: int = 0
        self._state: str = "closed"
        self._opened_at: float = 0.0

    def allow(self) -> bool:
        with self._lock:
            if self._state == "closed":
                return True
            if self._state == "open":
                now = self.clock()
                if now - self._opened_at >= self.cooldown_s:
                    self._state = "half_open"
                    return True
                return False
            if self._state == "half_open":
                return False
            return False

    def record(self, ok: bool) -> None:
        with self._lock:
            if self._state == "half_open":
                if ok:
                    self._state = "closed"
                    self._consecutive_failures = 0
                else:
                    self._state = "open"
                    self._opened_at = self.clock()
            elif self._state == "closed":
                if ok:
                    self._consecutive_failures = 0
                else:
                    self._consecutive_failures += 1
                    if self._consecutive_failures >= self.failures:
                        self._state = "open"
                        self._opened_at = self.clock()
            elif self._state == "open":
                pass


class SemanticCandidateSource:
    """Candidate source protected by deadline, circuit breaker, and bulkhead limits.

    Three protections isolate the chat flow from embedding failures:
    - Deadline: A slow embedder must not slow a chat turn. Lookups wait at most
      `settings.deadline_ms`. Exceeding this limit times out immediately and
      records a circuit breaker failure.
    - Breaker: Stop calling a failing embedder. Repeated timeouts or errors trip
      the breaker open to shed traffic without wasting resources on downstream calls.
      After `cooldown_s`, a probe call tests service health before closing.
    - Bulkhead: Bounded in-flight work so slow turns cannot pile up. Concurrency
      is capped by a bounded semaphore with capacity `2 * settings.threads`.
      Saturated queues reject immediately with 'queue_full' without tripping the
      breaker, and semaphore slots are retained until worker tasks finish.
    """

    def __init__(
        self,
        embedder: Any,
        index: Any,
        settings: SemanticSettings,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.embedder: Any = embedder
        self.index: Any = index
        self.settings: SemanticSettings = settings
        self.clock: Callable[[], float] = clock
        self.breaker: Breaker = Breaker(
            failures=settings.breaker_failures,
            cooldown_s=settings.breaker_cooldown_s,
            clock=clock,
        )
        self._executor: ThreadPoolExecutor = ThreadPoolExecutor(
            max_workers=settings.threads,
            thread_name_prefix="semantic",
        )
        self._semaphore: threading.BoundedSemaphore = threading.BoundedSemaphore(
            value=2 * settings.threads
        )

    def close(self) -> None:
        """Shut down the executor without waiting for pending futures."""
        self._executor.shutdown(wait=False, cancel_futures=True)

    def __enter__(self) -> SemanticCandidateSource:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

    def _release_slot(self, _future: Any = None) -> None:
        try:
            self._semaphore.release()
        except ValueError:
            pass

    def _run_embed_and_search(self, message: str) -> Any:
        with SEMANTIC_EMBED_DURATION.time():
            vector = self.embedder.embed(message)
            return self.index.search(vector, self.settings.top_n)

    def candidates(self, message: str) -> CandidateResult:
        try:
            # 1. empty: no alphanumeric characters (empty, whitespace, emoji, punctuation-only)
            if not message or not any(ch.isalnum() for ch in message):
                SEMANTIC_OUTCOMES.labels(outcome="empty").inc()
                return CandidateResult((), "empty")

            # 2. not ready: embedder not ready or index is None
            if self.embedder is None or not getattr(self.embedder, "ready", False) or self.index is None:
                SEMANTIC_OUTCOMES.labels(outcome="not_ready").inc()
                return CandidateResult((), "not_ready")

            # 3. admission (bulkhead): bounded concurrency. This comes BEFORE the breaker on
            # purpose: breaker.allow() may hand out the single half-open probe, and a probe
            # that is then rejected here would never be recorded, leaving the breaker stuck.
            if not self._semaphore.acquire(blocking=False):
                SEMANTIC_OUTCOMES.labels(outcome="queue_full").inc()
                return CandidateResult((), "queue_full")

            # 4. breaker: circuit breaker open or half-open without probe slot
            if not self.breaker.allow():
                self._release_slot()
                SEMANTIC_OUTCOMES.labels(outcome="breaker_open").inc()
                return CandidateResult((), "breaker_open")

            # 5. run in ThreadPoolExecutor
            try:
                future = self._executor.submit(self._run_embed_and_search, message)
            except Exception:
                self._release_slot()
                self.breaker.record(False)
                SEMANTIC_OUTCOMES.labels(outcome="error").inc()
                return CandidateResult((), "error")

            future.add_done_callback(self._release_slot)

            try:
                hits = future.result(timeout=self.settings.deadline_ms / 1000.0)
                candidates = tuple(
                    Candidate(
                        concept_id=h.row.concept_id,
                        anchor_id=h.row.anchor_id,
                        score=float(h.score),
                        text=h.row.text,
                    )
                    for h in (hits or ())
                )
            except (concurrent.futures.TimeoutError, TimeoutError):
                self.breaker.record(False)
                SEMANTIC_OUTCOMES.labels(outcome="timeout").inc()
                return CandidateResult((), "timeout")
            except ValueError:
                # Not an embedder fault, but a half-open probe must still be answered or the
                # breaker would wait for a result that never comes.
                self.breaker.record(True)
                SEMANTIC_OUTCOMES.labels(outcome="empty").inc()
                return CandidateResult((), "empty")
            except Exception:
                self.breaker.record(False)
                SEMANTIC_OUTCOMES.labels(outcome="error").inc()
                return CandidateResult((), "error")

            self.breaker.record(True)
            SEMANTIC_OUTCOMES.labels(outcome="ok").inc()
            return CandidateResult(candidates, None)
        except Exception:
            SEMANTIC_OUTCOMES.labels(outcome="error").inc()
            return CandidateResult((), "error")
