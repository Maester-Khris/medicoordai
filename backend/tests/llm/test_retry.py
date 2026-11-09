import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

import pytest

from llm.base import BaseLLMClient, LLMMessage, LLMResponse
from llm.retry import RetryingLLMClient, is_retryable
from observability import _registry


class _StatusError(Exception):
    def __init__(self, status_code: int) -> None:
        super().__init__(f"status {status_code}")
        self.status_code = status_code


class APIConnectionError(Exception):
    """Same name as the SDK class."""


class APITimeoutError(APIConnectionError):
    """In the Groq, OpenAI and Anthropic SDKs a timeout is a kind of connection error."""


class _ConnectionNamedStatusError(_StatusError):
    """A status error whose class name mentions Connection: the status code must win."""


_ConnectionNamedStatusError.__name__ = "ConnectionStatusError"


@pytest.mark.parametrize("exc,expected", [
    (_StatusError(429), True),
    (_StatusError(500), True),
    (_StatusError(502), True),
    (_StatusError(503), True),
    (ConnectionError("reset"), True),
    (ConnectionResetError("reset"), True),
    (APIConnectionError("dns"), True),
    (APITimeoutError("slow"), False),
    (TimeoutError("slow"), False),
    (_StatusError(400), False),
    (_StatusError(401), False),
    (_StatusError(403), False),
    (_StatusError(404), False),
    (ValueError("bad json"), False),
    (_ConnectionNamedStatusError(400), False),  # the status decides when there is one
    (_ConnectionNamedStatusError(503), True),
])
def test_is_retryable(exc: Exception, expected: bool) -> None:
    assert is_retryable(exc) is expected


class _Scripted(BaseLLMClient):
    """Raises or returns the scripted outcomes in order; the last one repeats."""

    def __init__(self, *outcomes: object) -> None:
        self._outcomes = list(outcomes)
        self.calls = 0

    @property
    def model_name(self) -> str:
        return "scripted-model"

    async def chat(self, messages, tools=None, temperature=0.2, stop=None, force_tool=None) -> LLMResponse:
        outcome = self._outcomes[min(self.calls, len(self._outcomes) - 1)]
        self.calls += 1
        if isinstance(outcome, Exception):
            raise outcome
        return LLMResponse(content=str(outcome), tool_calls=None, finish_reason="stop",
                           model=self.model_name, usage={"prompt_tokens": 1, "completion_tokens": 1})


MESSAGES = [LLMMessage(role="user", content="hello")]


class _Sleeps:
    def __init__(self) -> None:
        self.delays: list[float] = []

    async def __call__(self, delay: float) -> None:
        self.delays.append(delay)


def _client(inner: BaseLLMClient, attempts: int = 2, jitter: float = 1.0, sleeps: _Sleeps | None = None,
            base_delay: float = 0.25, max_delay: float = 1.0) -> RetryingLLMClient:
    return RetryingLLMClient(
        inner, provider="groq", attempts=attempts, base_delay=base_delay, max_delay=max_delay,
        sleep=sleeps or _Sleeps(), jitter=lambda: jitter,
    )


def _retries(provider: str = "groq") -> float:
    return _registry.get_sample_value("llm_retries_total", {"provider": provider}) or 0.0


def test_a_transient_failure_is_retried_once_and_the_answer_returned() -> None:
    inner, sleeps = _Scripted(_StatusError(503), "ok"), _Sleeps()
    before = _retries()
    assert asyncio.run(_client(inner, sleeps=sleeps).chat(MESSAGES)).content == "ok"
    assert inner.calls == 2
    assert len(sleeps.delays) == 1 and 0 < sleeps.delays[0] <= 1.0
    assert _retries() == before + 1


def test_when_every_attempt_fails_the_last_error_is_raised() -> None:
    last = _StatusError(503)
    inner = _Scripted(_StatusError(503), last)
    with pytest.raises(_StatusError) as caught:
        asyncio.run(_client(inner, attempts=2).chat(MESSAGES))
    assert caught.value is last
    assert inner.calls == 2


@pytest.mark.parametrize("failure", [_StatusError(400), _StatusError(401), APITimeoutError("slow"), ValueError("x")])
def test_a_failure_that_is_not_retryable_is_raised_after_one_call(failure: Exception) -> None:
    inner, sleeps = _Scripted(failure), _Sleeps()
    with pytest.raises(type(failure)):
        asyncio.run(_client(inner, sleeps=sleeps).chat(MESSAGES))
    assert inner.calls == 1
    assert sleeps.delays == []


def test_one_attempt_means_no_retry() -> None:
    inner = _Scripted(_StatusError(503), "ok")
    with pytest.raises(_StatusError):
        asyncio.run(_client(inner, attempts=1).chat(MESSAGES))
    assert inner.calls == 1


def test_the_delay_is_full_jitter_within_the_base_and_never_above_the_maximum() -> None:
    sleeps = _Sleeps()
    inner = _Scripted(*([_StatusError(503)] * 5), "ok")
    asyncio.run(_client(inner, attempts=6, jitter=1.0, sleeps=sleeps).chat(MESSAGES))
    assert sleeps.delays[0] == pytest.approx(0.25)
    assert max(sleeps.delays) <= 1.0

    sleeps = _Sleeps()
    asyncio.run(_client(_Scripted(_StatusError(503), "ok"), jitter=0.0, sleeps=sleeps).chat(MESSAGES))
    assert sleeps.delays == [0.0]


def test_a_success_on_the_first_call_never_sleeps_or_counts_a_retry() -> None:
    inner, sleeps = _Scripted("ok"), _Sleeps()
    before = _retries()
    asyncio.run(_client(inner, sleeps=sleeps).chat(MESSAGES))
    assert sleeps.delays == [] and _retries() == before


def test_the_model_name_is_the_inner_clients() -> None:
    assert _client(_Scripted("ok")).model_name == "scripted-model"


def test_fewer_than_one_attempt_is_rejected() -> None:
    with pytest.raises(ValueError):
        _client(_Scripted("ok"), attempts=0)
