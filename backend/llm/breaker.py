"""Per-provider circuit breaker for LLM clients.

Why it exists: a failing provider is skipped at once instead of costing a timeout per call;
one probe tests recovery after a cooldown; per-process by design, a shared breaker is the
future gateway's job.
"""
import time
from collections.abc import Callable

try:
    from metrics import LLM_BREAKER_TRANSITIONS
except ImportError:
    from backend.metrics import LLM_BREAKER_TRANSITIONS

from .base import BaseLLMClient, LLMMessage, LLMResponse, ToolDefinition
from .instrumented import worth_trying_another_provider


class ProviderCircuitOpen(Exception):
    """Raised when calls to an LLM provider are blocked by an open circuit breaker."""

    status_code: int = 503

    def __init__(self, provider: str) -> None:
        super().__init__(f"Provider circuit open: {provider}")
        self.provider: str = provider
        self.status_code: int = 503


class CircuitBreakerLLMClient(BaseLLMClient):
    """Wraps an LLM provider client with a circuit breaker.

    Why it exists: a failing provider is skipped at once instead of costing a timeout per call;
    one probe tests recovery after a cooldown; per-process by design, a shared breaker is the
    future gateway's job.
    """

    def __init__(
        self,
        inner: BaseLLMClient,
        provider: str,
        failure_threshold: int,
        cooldown_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._inner = inner
        self.provider = provider
        self._failure_threshold = failure_threshold
        self._cooldown_seconds = cooldown_seconds
        self._clock = clock
        self._state: str = "closed"
        self._failures: int = 0
        self._opened_at: float = 0.0

    @property
    def state(self) -> str:
        return self._state

    @property
    def model_name(self) -> str:
        return self._inner.model_name

    def _transition_to(self, to: str) -> None:
        self._state = to
        LLM_BREAKER_TRANSITIONS.labels(provider=self.provider, to=to).inc()

    async def chat(
        self,
        messages: list[LLMMessage],
        tools: list[ToolDefinition] | None = None,
        temperature: float = 0.2,
        stop: list[str] | None = None,
        force_tool: str | None = None,
    ) -> LLMResponse:
        is_probe = False
        if self._state == "open":
            now = self._clock()
            if now - self._opened_at < self._cooldown_seconds:
                raise ProviderCircuitOpen(self.provider)
            self._transition_to("half_open")
            is_probe = True
        elif self._state == "half_open":
            raise ProviderCircuitOpen(self.provider)

        if is_probe:
            try:
                response = await self._inner.chat(
                    messages=messages,
                    tools=tools,
                    temperature=temperature,
                    stop=stop,
                    force_tool=force_tool,
                )
            except Exception as exc:
                if worth_trying_another_provider(exc):
                    self._opened_at = self._clock()
                    self._transition_to("open")
                else:
                    self._failures = 0
                    self._transition_to("closed")
                raise
            else:
                self._failures = 0
                self._transition_to("closed")
                return response
        else:
            try:
                response = await self._inner.chat(
                    messages=messages,
                    tools=tools,
                    temperature=temperature,
                    stop=stop,
                    force_tool=force_tool,
                )
            except Exception as exc:
                if worth_trying_another_provider(exc):
                    self._failures += 1
                    if self._state == "closed" and self._failures >= self._failure_threshold:
                        self._opened_at = self._clock()
                        self._transition_to("open")
                else:
                    self._failures = 0
                raise
            else:
                if self._state == "closed":
                    self._failures = 0
                return response
