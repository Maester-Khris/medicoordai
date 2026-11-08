"""Narrow retry policy with exponential backoff and full jitter for transient LLM provider failures.

429 (rate limits), 5xx (server errors), and connection resets are transient and the next attempt
can succeed. 400 (bad request/client errors) and timeouts are not retried because a retry repeats
the cost or the wait. Full jitter avoids a retry storm when multiple requests fail simultaneously.
"""
import asyncio
from collections.abc import Awaitable, Callable
import random
from typing import Any

from metrics import LLM_RETRIES

from .base import BaseLLMClient, LLMMessage, LLMResponse, ToolDefinition
from .instrumented import classify_llm_error

# Named so the eval run manifest can record the values that shape a retry.
BASE_DELAY_SECONDS = 0.25
MAX_DELAY_SECONDS = 1.0


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
                LLM_RETRIES.labels(provider=self.provider).inc()
                delay = self._jitter() * min(self.max_delay, self.base_delay * (2 ** attempt))
                await self._sleep(delay)
        raise AssertionError("unreachable: the last attempt returns or raises")
