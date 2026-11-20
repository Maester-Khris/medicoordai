import threading
import time
from pathlib import Path

import numpy as np
import pytest

from graph.semantic.candidates import Breaker, Candidate, CandidateResult, SemanticCandidateSource
from graph.semantic.index import Hit, IndexRow
from graph.semantic.settings import SemanticSettings
from metrics import _registry


def _settings(**kw):
    base = dict(model_dir=Path("/m"), index_dir=Path("/i"), score_threshold=0.5, gap_margin=0.02, lay_rule="confirmed",
                threads=1, deadline_ms=200, top_n=2)
    base.update(kw)
    return SemanticSettings(**base)


class FakeEmbedder:
    name, dim = "fake", 2

    def __init__(self, ready=True, delay=0.0, fail=False, gate=None):
        self.ready, self.delay, self.fail, self.gate = ready, delay, fail, gate
        self.calls = []

    def embed(self, text):
        self.calls.append(text)
        if self.gate is not None:
            self.gate.wait(5)
        if self.fail:
            raise RuntimeError("model blew up")
        time.sleep(self.delay)
        return np.array([1.0, 0.0], dtype=np.float32)


class FakeIndex:
    def __init__(self):
        self.rows = [IndexRow("c1", "a1", "headache", "english"), IndexRow("c2", "a2", "cough", "english"),
                     IndexRow("c3", "a3", "rash", "english")]

    def search(self, vector, top_n):
        return [Hit(r, s) for r, s in zip(self.rows, (0.9, 0.7, 0.4))][:top_n]


def _outcome(name):
    return _registry.get_sample_value("graph_semantic_outcomes_total", {"outcome": name}) or 0.0


def _source(embedder=None, **kw):
    return SemanticCandidateSource(embedder or FakeEmbedder(), FakeIndex(), _settings(**kw))


@pytest.mark.parametrize("message", ["", "   ", "😀😀", "?!...", "\n"])
def test_whitespace_or_emoji_only_message_is_skipped_as_empty(message):
    embedder = FakeEmbedder()
    result = _source(embedder).candidates(message)
    assert result == CandidateResult((), "empty") and embedder.calls == []


def test_top_n_hits_become_candidates_with_anchor_ids():
    before = _outcome("ok")
    result = _source().candidates("my head hurts")
    assert result.skipped is None
    assert result.candidates == (Candidate("c1", "a1", 0.9, "headache"), Candidate("c2", "a2", 0.7, "cough"))
    assert _outcome("ok") == before + 1


def test_slow_embedder_beyond_deadline_returns_timeout():
    gate = threading.Event()
    source = _source(FakeEmbedder(gate=gate), deadline_ms=50)
    started = time.monotonic()
    result = source.candidates("my head hurts")
    assert result == CandidateResult((), "timeout") and time.monotonic() - started < 0.5
    gate.set()


def test_second_concurrent_turn_with_full_queue_returns_queue_full_without_waiting():
    gate = threading.Event()
    source = _source(FakeEmbedder(gate=gate), deadline_ms=2000)  # threads=1: one running + one queued fills capacity
    results = []
    workers = [threading.Thread(target=lambda: results.append(source.candidates("my head hurts"))) for _ in range(2)]
    for w in workers:
        w.start()
    time.sleep(0.15)  # both are now admitted and blocked on the gate
    started = time.monotonic()
    third = source.candidates("my head hurts")
    assert third == CandidateResult((), "queue_full") and time.monotonic() - started < 0.1
    gate.set()
    for w in workers:
        w.join(3)
    assert all(r.skipped is None for r in results)  # the admitted turns still finish normally
    assert source.candidates("my head hurts").skipped is None  # capacity is released afterwards


def test_breaker_opens_after_n_failures_and_half_opens_after_cooldown():
    now = [100.0]
    breaker = Breaker(failures=2, cooldown_s=30.0, clock=lambda: now[0])
    assert breaker.allow()
    breaker.record(False)
    assert breaker.allow()
    breaker.record(False)
    assert not breaker.allow()
    now[0] += 29
    assert not breaker.allow()
    now[0] += 2
    assert breaker.allow()  # half-open: one probe
    assert not breaker.allow()  # a second caller does not also probe
    breaker.record(False)  # failed probe reopens for another cooldown
    assert not breaker.allow()
    now[0] += 31
    assert breaker.allow()
    breaker.record(True)
    assert breaker.allow() and breaker.allow()  # closed again


def test_source_failures_open_the_breaker_then_skip_without_calling_the_embedder():
    embedder = FakeEmbedder(fail=True)
    source = _source(embedder, breaker_failures=2)
    assert source.candidates("my head hurts").skipped == "error"
    assert source.candidates("my head hurts").skipped == "error"
    calls = len(embedder.calls)
    assert source.candidates("my head hurts") == CandidateResult((), "breaker_open")
    assert len(embedder.calls) == calls


def test_not_ready_embedder_is_skipped():
    embedder = FakeEmbedder(ready=False)
    assert _source(embedder).candidates("my head hurts") == CandidateResult((), "not_ready")
    assert embedder.calls == []


def _clocked(embedder, **kw):
    now = [100.0]
    source = SemanticCandidateSource(embedder, FakeIndex(), _settings(**kw), clock=lambda: now[0])
    return source, now


def test_a_rejected_turn_does_not_consume_the_half_open_probe():
    gate = threading.Event()
    source, now = _clocked(FakeEmbedder(gate=gate), deadline_ms=30, breaker_failures=2)
    assert source.candidates("my head hurts").skipped == "timeout"
    assert source.candidates("my head hurts").skipped == "timeout"  # both slots are now held by hung workers
    now[0] += 31
    assert source.candidates("my head hurts").skipped == "queue_full"  # rejected before the breaker hands out the probe
    gate.set()
    time.sleep(0.2)  # the hung workers finish and free their slots
    assert source.candidates("my head hurts").skipped is None  # the probe was still available, and it succeeds


def test_an_embedder_value_error_does_not_leave_the_probe_stuck():
    embedder = FakeEmbedder(fail=True)
    source, now = _clocked(embedder, breaker_failures=1)
    assert source.candidates("my head hurts").skipped == "error"
    now[0] += 31
    embedder.fail = False

    def raise_value_error(text):
        raise ValueError("empty text")

    embedder.embed = raise_value_error
    assert source.candidates("my head hurts").skipped == "empty"
    del embedder.embed  # back to the class implementation, which works
    assert source.candidates("my head hurts").skipped is None
