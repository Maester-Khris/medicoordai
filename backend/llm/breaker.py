"""Per-provider circuit breaker for LLM clients.

Why it exists: a failing provider is skipped at once instead of costing a timeout per call;
one probe tests recovery after a cooldown; per-process by design, a shared breaker is the
future gateway's job.
"""
import time
from collections.abc import Callable
from typing import Literal

from metrics import LLM_BREAKER_TRANSITIONS

from .base import BaseLLMClient, LLMMessage, LLMResponse, ToolDefinition
from .instrumented import worth_trying_another_provider


State = Literal["closed", "open", "half_open"]


class ProviderCircuitOpen(Exception):
    """Raised when calls to an LLM provider are blocked by an open circuit breaker.

    status_code 503 makes worth_trying_another_provider treat it as a provider failure, so the
    fallback chain moves to the next provider.
    """

    status_code = 503

    def __init__(self, provider: str) -> None:
        super().__init__(f"Provider circuit open: {provider}")
        self.provider = provider


class CircuitBreakerLLMClient(BaseLLMClient):
    """closed -> open after `failure_threshold` consecutive provider-side failures; open -> half_open
    after the cooldown, when exactly one call is let through as a probe; the probe closes it on
    success and reopens it (fresh cooldown) on a provider-side failure or a cancellation.

    A request error (a 400) means the provider answered, so it counts as success for the breaker.
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
        self._state: State = "closed"
        self._failures = 0
        self._opened_at = 0.0

    @property
    def state(self) -> State:
        return self._state

    @property
    def model_name(self) -> str:
        return self._inner.model_name

    def _transition_to(self, to: State) -> None:
        self._state = to
        LLM_BREAKER_TRANSITIONS.labels(provider=self.provider, to=to).inc()

    def _open(self) -> None:
        self._opened_at = self._clock()
        self._transition_to("open")

    def _admit(self) -> bool:
        """Raise when the call must not go through; True when this call is the probe.

        Runs before any await: the state change and the "probe taken" mark are one atomic step in
        asyncio, so only one caller can become the probe.
        """
        if self._state == "half_open":
            raise ProviderCircuitOpen(self.provider)
        if self._state == "open":
            if self._clock() - self._opened_at < self._cooldown_seconds:
                raise ProviderCircuitOpen(self.provider)
            self._transition_to("half_open")
            return True
        return False

    def _record_failure(self, exc: BaseException, is_probe: bool) -> None:
        if not isinstance(exc, Exception):
            # Cancelled (a wait_for around the call, a shutdown): no verdict on the provider. A probe
            # that never reported must not leave the breaker half-open for good.
            if is_probe:
                self._open()
            return
        if worth_trying_another_provider(exc):
            self._failures += 1
            if is_probe or (self._state == "closed" and self._failures >= self._failure_threshold):
                self._open()
            return
        self._record_success(is_probe)

    def _record_success(self, is_probe: bool) -> None:
        self._failures = 0
        if is_probe:
            self._transition_to("closed")

    async def chat(
        self,
        messages: list[LLMMessage],
        tools: list[ToolDefinition] | None = None,
        temperature: float = 0.2,
        stop: list[str] | None = None,
        force_tool: str | None = None,
    ) -> LLMResponse:
        is_probe = self._admit()
        try:
            response = await self._inner.chat(
                messages=messages, tools=tools, temperature=temperature, stop=stop, force_tool=force_tool,
            )
        except BaseException as exc:
            self._record_failure(exc, is_probe)
            raise
        self._record_success(is_probe)
        return response
