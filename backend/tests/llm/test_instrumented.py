import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

import pytest

from llm.base import BaseLLMClient, LLMMessage, LLMResponse
from llm.instrumented import InstrumentedLLMClient, classify_llm_error, worth_trying_another_provider
from observability import _registry


class _StatusError(Exception):
    def __init__(self, status_code: int) -> None:
        super().__init__(f"status {status_code}")
        self.status_code = status_code


class APITimeoutError(Exception):
    """Same name as the SDK timeout classes; the classifier goes by name."""


class APIConnectionError(Exception):
    """Same name as the SDK connection-failure classes."""


@pytest.mark.parametrize("exc,expected", [
    (_StatusError(429), "rate_limited"),
    (APITimeoutError("slow"), "timeout"),
    (TimeoutError("slow"), "timeout"),
    (_StatusError(503), "error"),
    (_StatusError(400), "error"),
    (ValueError("bad json"), "error"),
])
def test_classify_llm_error(exc: Exception, expected: str) -> None:
    assert classify_llm_error(exc) == expected


@pytest.mark.parametrize("exc,expected", [
    (_StatusError(429), True),
    (APITimeoutError("slow"), True),
    (_StatusError(500), True),
    (_StatusError(503), True),
    (APIConnectionError("dns"), True),
    (ConnectionResetError("reset"), True),
    (_StatusError(401), True),
    (_StatusError(403), True),
    (_StatusError(400), False),
    (_StatusError(404), False),
    (_StatusError(422), False),
    (ValueError("bad json"), False),
    (KeyError("choices"), False),
])
def test_worth_trying_another_provider(exc: Exception, expected: bool) -> None:
    assert worth_trying_another_provider(exc) is expected


class _Fake(BaseLLMClient):
    def __init__(self, result: object) -> None:
        self.result = result
        self.calls: list[dict] = []

    @property
    def model_name(self) -> str:
        return "fake-model"

    def chat(self, messages, tools=None, temperature=0.2, stop=None, force_tool=None) -> LLMResponse:
        self.calls.append({"messages": messages, "tools": tools, "temperature": temperature,
                           "stop": stop, "force_tool": force_tool})
        if isinstance(self.result, Exception):
            raise self.result
        return self.result  # type: ignore[return-value]


def _response(prompt: int = 11, completion: int = 5) -> LLMResponse:
    return LLMResponse(content="hi", tool_calls=None, finish_reason="stop", model="fake-model",
                       usage={"prompt_tokens": prompt, "completion_tokens": completion})


def _value(name: str, **labels: str) -> float:
    return _registry.get_sample_value(name, labels) or 0.0


MESSAGES = [LLMMessage(role="user", content="hello")]


def test_a_successful_call_is_timed_counted_and_its_tokens_added() -> None:
    labels = {"provider": "probe-ok", "outcome": "ok"}
    client = InstrumentedLLMClient(_Fake(_response(prompt=11, completion=5)), "probe-ok")

    assert client.chat(MESSAGES).content == "hi"

    assert _value("llm_calls_total", **labels) == 1
    assert _value("llm_call_duration_seconds_count", **labels) == 1
    assert _value("llm_tokens_total", provider="probe-ok", kind="prompt") == 11
    assert _value("llm_tokens_total", provider="probe-ok", kind="completion") == 5


@pytest.mark.parametrize("exc,outcome", [
    (_StatusError(429), "rate_limited"),
    (APITimeoutError("slow"), "timeout"),
    (_StatusError(500), "error"),
])
def test_a_failed_call_is_counted_under_its_outcome_and_re_raised(exc: Exception, outcome: str) -> None:
    provider = f"probe-{outcome}"
    client = InstrumentedLLMClient(_Fake(exc), provider)

    with pytest.raises(type(exc)) as caught:
        client.chat(MESSAGES)

    assert caught.value is exc
    assert _value("llm_calls_total", provider=provider, outcome=outcome) == 1
    assert _value("llm_call_duration_seconds_count", provider=provider, outcome=outcome) == 1
    assert _value("llm_calls_total", provider=provider, outcome="ok") == 0
    assert _value("llm_tokens_total", provider=provider, kind="prompt") == 0


def test_arguments_and_model_name_pass_through_unchanged() -> None:
    inner = _Fake(_response())
    client = InstrumentedLLMClient(inner, "probe-args")
    client.chat(MESSAGES, tools=["t"], temperature=0.7, stop=["END"], force_tool="triage_response")  # type: ignore[list-item]
    assert inner.calls == [{"messages": MESSAGES, "tools": ["t"], "temperature": 0.7,
                            "stop": ["END"], "force_tool": "triage_response"}]
    assert client.model_name == "fake-model" and client.provider == "probe-args"


def test_missing_usage_does_not_break_the_call() -> None:
    response = _response()
    response.usage = {}
    assert InstrumentedLLMClient(_Fake(response), "probe-nousage").chat(MESSAGES) is response


def _sdk_errors(module) -> dict[str, Exception]:
    import httpx

    request = httpx.Request("POST", "https://provider.invalid/v1/chat")

    def status(cls, code: int) -> Exception:
        return cls("boom", response=httpx.Response(code, request=request), body=None)

    return {
        "rate_limit": status(module.RateLimitError, 429),
        "server": status(module.InternalServerError, 500),
        "bad_request": status(module.BadRequestError, 400),
        "auth": status(module.AuthenticationError, 401),
        "timeout": module.APITimeoutError(request=request),
        "connection": module.APIConnectionError(request=request),
    }


@pytest.mark.parametrize("sdk_name", ["groq", "openai", "anthropic"])
def test_real_sdk_exceptions_are_classified_as_expected(sdk_name: str) -> None:
    import importlib

    errors = _sdk_errors(importlib.import_module(sdk_name))
    assert {name: classify_llm_error(exc) for name, exc in errors.items()} == {
        "rate_limit": "rate_limited", "server": "error", "bad_request": "error",
        "auth": "error", "timeout": "timeout", "connection": "error",
    }
    assert {name: worth_trying_another_provider(exc) for name, exc in errors.items()} == {
        "rate_limit": True, "server": True, "bad_request": False,
        "auth": True, "timeout": True, "connection": True,
    }
