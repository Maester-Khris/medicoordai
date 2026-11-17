"""Narrow retry policy with exponential backoff and full jitter for transient LLM provider failures.

429 (rate limits), 5xx (server errors), and connection resets are transient and the next attempt
can succeed. 400 (bad request/client errors) and timeouts are not retried because a retry repeats
the cost or the wait. Full jitter avoids a retry storm when multiple requests fail simultaneously.
"""
import asyncio
from collections import deque
from collections.abc import Awaitable, Callable
import random
import time
from typing import Any

import config
from metrics import LLM_RETRIES, LLM_RETRY_BUDGET_EXHAUSTED

from .base import BaseLLMClient, LLMMessage, LLMResponse, ToolDefinition
from .instrumented import classify_llm_error

# Named so the eval run manifest can record the values that shape a retry.
BASE_DELAY_SECONDS = 0.25
MAX_DELAY_SECONDS = 1.0


class RetryBudget:
    """Process-wide rolling-window cap on LLM retries.

    SDK and per-call retries multiply provider traffic exactly when a provider is
    struggling (a retry storm). The cap is per process; it is not shared between replicas.
    """

    def __init__(
        self,
        percent: int,
        window_seconds: float = 60.0,
        floor: int = 3,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._percent = percent
        self._window_seconds = window_seconds
        self._floor = floor
        self._clock = clock
        self._calls: deque[float] = deque()
        self._retries: deque[float] = deque()

    def _prune(self, now: float) -> None:
        cutoff = now - self._window_seconds
        while self._calls and self._calls[0] <= cutoff:
            self._calls.popleft()
        while self._retries and self._retries[0] <= cutoff:
            self._retries.popleft()

    def record_call(self) -> None:
        """Record that one call to a provider happened."""
        now = self._clock()
        self._prune(now)
        self._calls.append(now)

    def allow_retry(self) -> bool:
        """Return True and record a retry if retries in the window are still within budget."""
        now = self._clock()
        self._prune(now)
        limit = max(self._floor, self._percent / 100 * len(self._calls))
        if len(self._retries) < limit:
            self._retries.append(now)
            return True
        return False


_shared_budget: RetryBudget | None = None


def shared_retry_budget() -> RetryBudget:
    """Return the single process-wide RetryBudget, built lazily from config."""
    global _shared_budget
    if _shared_budget is None:
        _shared_budget = RetryBudget(percent=config.retry_budget_percent())
    return _shared_budget


def is_retryable(exc: BaseException) -> bool:
    """True for transient errors (429, 5xx, ConnectionError); False for timeouts and client errors."""
    if classify_llm_error(exc) == "timeout":
        return False
    status = getattr(exc, "status_code", None)
    if isinstance(status, int) and not isinstance(status, bool):
        return status == 429 or status >= 500  # with a status, the status alone decides
    return isinstance(exc, ConnectionError) or any("Connection" in cls.__name__ for cls in type(exc).__mro__)


class RetryingLLMClient(BaseLLMClient):
    """Wraps an LLM client with retries for transient failures.

    429/5xx/connection resets are transient and the next attempt can succeed;
    400 and timeouts are not retried because a retry repeats the cost or the wait;
    full jitter avoids a retry storm.
    """

    def __init__(
        self,
        inner: BaseLLMClient,
        provider: str,
        attempts: int,
        base_delay: float = BASE_DELAY_SECONDS,
        max_delay: float = MAX_DELAY_SECONDS,
        sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
        jitter: Callable[[], float] = random.random,
        budget: RetryBudget | None = None,
    ) -> None:
        if attempts < 1:
            raise ValueError("attempts must be at least 1")
        self._inner = inner
        self.provider = provider
        self.attempts = attempts
        self.base_delay = base_delay
        self.max_delay = max_delay
        self._sleep = sleep
        self._jitter = jitter
        self._budget = budget

    @property
    def model_name(self) -> str:
        return self._inner.model_name

    async def chat(
        self,
        messages: list[LLMMessage],
        tools: list[ToolDefinition] | None = None,
        temperature: float = 0.2,
        stop: list[str] | None = None,
        force_tool: str | None = None,
    ) -> LLMResponse:
        if self._budget is not None:
            self._budget.record_call()
        for attempt in range(self.attempts):
            try:
                return await self._inner.chat(
                    messages=messages,
                    tools=tools,
                    temperature=temperature,
                    stop=stop,
                    force_tool=force_tool,
                )
            except Exception as exc:
                if not is_retryable(exc) or attempt >= self.attempts - 1:
                    raise
                if self._budget is not None and not self._budget.allow_retry():
                    LLM_RETRY_BUDGET_EXHAUSTED.labels(provider=self.provider).inc()
                    raise
                LLM_RETRIES.labels(provider=self.provider).inc()
                delay = self._jitter() * min(self.max_delay, self.base_delay * (2 ** attempt))
                await self._sleep(delay)
        raise AssertionError("unreachable: the last attempt returns or raises")
