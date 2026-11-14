import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

import pytest

from llm.base import BaseLLMClient, LLMMessage, LLMResponse
from llm.breaker import CircuitBreakerLLMClient, ProviderCircuitOpen
from llm.instrumented import worth_trying_another_provider
from observability import _registry


class _StatusError(Exception):
    def __init__(self, status_code: int) -> None:
        super().__init__(f"status {status_code}")
        self.status_code = status_code


class APITimeoutError(Exception):
    pass


class _Scripted(BaseLLMClient):
    def __init__(self, *outcomes: object) -> None:
        self.outcomes = list(outcomes)
        self.calls = 0
        self.gate: asyncio.Event | None = None  # when set, a call waits here before answering

    @property
    def model_name(self) -> str:
        return "scripted-model"

    async def chat(self, messages, tools=None, temperature=0.2, stop=None, force_tool=None) -> LLMResponse:
        outcome = self.outcomes[min(self.calls, len(self.outcomes) - 1)]
        self.calls += 1
        if self.gate is not None:
            await self.gate.wait()
        if isinstance(outcome, BaseException):
            raise outcome
        return LLMResponse(content=str(outcome), tool_calls=None, finish_reason="stop",
                           model=self.model_name, usage={"prompt_tokens": 1, "completion_tokens": 1})


MESSAGES = [LLMMessage(role="user", content="hello")]
THRESHOLD, COOLDOWN = 3, 30.0


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _breaker(inner: BaseLLMClient, clock: _Clock, provider: str = "groq") -> CircuitBreakerLLMClient:
    return CircuitBreakerLLMClient(inner, provider=provider, failure_threshold=THRESHOLD,
                                   cooldown_seconds=COOLDOWN, clock=clock)


def _call(client: CircuitBreakerLLMClient) -> str:
    return asyncio.run(client.chat(MESSAGES)).content


def _fail(client: CircuitBreakerLLMClient, times: int, error: Exception) -> None:
    for _ in range(times):
        with pytest.raises(type(error)):
            asyncio.run(client.chat(MESSAGES))


def test_failures_below_the_threshold_keep_it_closed_and_a_success_resets_the_count() -> None:
    inner = _Scripted(_StatusError(503), _StatusError(503), "ok", _StatusError(503), _StatusError(503), "ok")
    client = _breaker(inner, _Clock())
    _fail(client, 2, _StatusError(503))
    assert _call(client) == "ok"
    _fail(client, 2, _StatusError(503))
    assert client.state == "closed"
    assert _call(client) == "ok"


@pytest.mark.parametrize("failure", [_StatusError(503), _StatusError(429), APITimeoutError("slow"),
                                     ConnectionResetError("reset")])
def test_consecutive_provider_failures_open_it_and_an_open_breaker_does_not_call_the_provider(failure: Exception) -> None:
    inner = _Scripted(failure)
    client = _breaker(inner, _Clock())
    _fail(client, THRESHOLD, failure)
    assert client.state == "open"
    with pytest.raises(ProviderCircuitOpen):
        asyncio.run(client.chat(MESSAGES))
    assert inner.calls == THRESHOLD


def test_a_request_error_does_not_count_and_resets_the_failure_count() -> None:
    inner = _Scripted(*([_StatusError(503)] * 2), _StatusError(400), *([_StatusError(503)] * 2))
    client = _breaker(inner, _Clock())
    _fail(client, 2, _StatusError(503))
    _fail(client, 1, _StatusError(400))
    _fail(client, 2, _StatusError(503))
    assert client.state == "closed"


def test_after_the_cooldown_one_probe_closes_the_breaker_when_it_succeeds() -> None:
    clock = _Clock()
    inner = _Scripted(*([_StatusError(503)] * THRESHOLD), "ok")
    client = _breaker(inner, clock)
    _fail(client, THRESHOLD, _StatusError(503))
    clock.now += COOLDOWN - 1
    with pytest.raises(ProviderCircuitOpen):
        asyncio.run(client.chat(MESSAGES))
    clock.now += 1
    assert _call(client) == "ok"
    assert client.state == "closed"


def test_a_failed_probe_reopens_it_for_another_full_cooldown() -> None:
    clock = _Clock()
    inner = _Scripted(_StatusError(503))
    client = _breaker(inner, clock)
    _fail(client, THRESHOLD, _StatusError(503))
    clock.now += COOLDOWN
    _fail(client, 1, _StatusError(503))
    assert client.state == "open"
    clock.now += COOLDOWN - 1
    with pytest.raises(ProviderCircuitOpen):
        asyncio.run(client.chat(MESSAGES))
    clock.now += 1
    calls_before = inner.calls
    _fail(client, 1, _StatusError(503))
    assert inner.calls == calls_before + 1


def test_half_open_lets_exactly_one_probe_through() -> None:
    async def scenario() -> tuple[str, str]:
        clock = _Clock()
        inner = _Scripted(*([_StatusError(503)] * THRESHOLD), "ok")
        client = _breaker(inner, clock)
        for _ in range(THRESHOLD):
            with pytest.raises(_StatusError):
                await client.chat(MESSAGES)
        clock.now += COOLDOWN
        inner.gate = asyncio.Event()
        probe = asyncio.ensure_future(client.chat(MESSAGES))
        await asyncio.sleep(0)  # the probe is now waiting on the gate
        with pytest.raises(ProviderCircuitOpen):
            await client.chat(MESSAGES)
        state_during = client.state
        inner.gate.set()
        answer = await probe
        return state_during, answer.content

    state_during, answer = asyncio.run(scenario())
    assert state_during == "half_open"
    assert answer == "ok"


def test_the_open_error_reads_as_a_provider_failure_to_the_fallback() -> None:
    error = ProviderCircuitOpen("groq")
    assert error.status_code == 503
    assert worth_trying_another_provider(error) is True


def _transitions(provider: str, to: str) -> float:
    return _registry.get_sample_value("llm_breaker_transitions_total", {"provider": provider, "to": to}) or 0.0


def test_every_state_change_is_counted() -> None:
    clock = _Clock()
    provider = "breaker-metric-test"
    before = {to: _transitions(provider, to) for to in ("open", "half_open", "closed")}
    inner = _Scripted(*([_StatusError(503)] * THRESHOLD), "ok")
    client = _breaker(inner, clock, provider=provider)
    _fail(client, THRESHOLD, _StatusError(503))
    clock.now += COOLDOWN
    _call(client)
    assert {to: _transitions(provider, to) - before[to] for to in before} == {"open": 1, "half_open": 1, "closed": 1}


def test_the_model_name_is_the_inner_clients() -> None:
    assert _breaker(_Scripted("ok"), _Clock()).model_name == "scripted-model"


def test_a_cancelled_probe_does_not_leave_the_breaker_half_open_for_good() -> None:
    clock = _Clock()
    inner = _Scripted(*([_StatusError(503)] * THRESHOLD), asyncio.CancelledError(), "ok")
    client = _breaker(inner, clock)
    _fail(client, THRESHOLD, _StatusError(503))
    clock.now += COOLDOWN
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(client.chat(MESSAGES))  # the probe is cancelled (a wait_for around the call, a shutdown)
    assert client.state == "open"
    clock.now += COOLDOWN
    assert _call(client) == "ok"
    assert client.state == "closed"


def test_a_cancelled_call_is_not_a_provider_failure() -> None:
    inner = _Scripted(_StatusError(503), _StatusError(503), asyncio.CancelledError(), _StatusError(503))
    client = _breaker(inner, _Clock())
    _fail(client, 2, _StatusError(503))
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(client.chat(MESSAGES))
    assert client.state == "closed"
