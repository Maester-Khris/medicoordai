import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

import logging

import pytest

from llm.base import BaseLLMClient, LLMMessage, LLMResponse
from llm.fallback import FallbackLLMClient


class _StatusError(Exception):
    def __init__(self, status_code: int) -> None:
        super().__init__(f"status {status_code}")
        self.status_code = status_code


class APITimeoutError(Exception):
    pass


class _Fake(BaseLLMClient):
    def __init__(self, provider: str, result: object) -> None:
        self.provider = provider
        self.result = result
        self.calls = 0

    @property
    def model_name(self) -> str:
        return f"{self.provider}-model"

    def chat(self, messages, tools=None, temperature=0.2, stop=None, force_tool=None) -> LLMResponse:
        self.calls += 1
        if isinstance(self.result, Exception):
            raise self.result
        return LLMResponse(content=str(self.result), tool_calls=None, finish_reason="stop",
                           model=self.model_name, usage={"prompt_tokens": 1, "completion_tokens": 1})


MESSAGES = [LLMMessage(role="user", content="hello")]


def test_the_first_provider_answers_and_the_others_are_not_called() -> None:
    first, second = _Fake("groq", "from groq"), _Fake("openai", "from openai")
    client = FallbackLLMClient([first, second])
    assert client.chat(MESSAGES).content == "from groq"
    assert (first.calls, second.calls) == (1, 0)
    assert client.model_name == "groq-model"


@pytest.mark.parametrize("failure", [_StatusError(429), APITimeoutError("slow"), _StatusError(503),
                                     _StatusError(401), ConnectionResetError("reset")])
def test_a_provider_side_failure_moves_to_the_next_provider(failure: Exception) -> None:
    first, second = _Fake("groq", failure), _Fake("openai", "from openai")
    client = FallbackLLMClient([first, second])
    assert client.chat(MESSAGES).content == "from openai"
    assert (first.calls, second.calls) == (1, 1)
    assert client.model_name == "openai-model"


@pytest.mark.parametrize("failure", [_StatusError(400), _StatusError(422), ValueError("bad json")])
def test_a_request_side_failure_is_raised_without_trying_another_provider(failure: Exception) -> None:
    first, second = _Fake("groq", failure), _Fake("openai", "from openai")
    with pytest.raises(type(failure)) as caught:
        FallbackLLMClient([first, second]).chat(MESSAGES)
    assert caught.value is failure
    assert second.calls == 0


def test_when_every_provider_fails_the_last_error_is_raised_and_each_was_tried_once() -> None:
    first_error, last_error = _StatusError(429), _StatusError(429)
    clients = [_Fake("groq", first_error), _Fake("openai", APITimeoutError("slow")), _Fake("anthropic", last_error)]
    with pytest.raises(_StatusError) as caught:
        FallbackLLMClient(clients).chat(MESSAGES)
    assert caught.value is last_error
    assert [c.calls for c in clients] == [1, 1, 1]


def test_each_call_starts_again_from_the_first_provider() -> None:
    first, second = _Fake("groq", _StatusError(429)), _Fake("openai", "from openai")
    client = FallbackLLMClient([first, second])
    client.chat(MESSAGES)
    client.chat(MESSAGES)
    assert (first.calls, second.calls) == (2, 2)


def test_a_switch_is_logged_with_both_providers_and_the_outcome(caplog: pytest.LogCaptureFixture) -> None:
    client = FallbackLLMClient([_Fake("groq", _StatusError(429)), _Fake("openai", "ok")])
    with caplog.at_level(logging.WARNING):
        client.chat(MESSAGES)
    records = [r for r in caplog.records if r.getMessage() == "llm_fallback"]
    assert len(records) == 1
    assert (records[0].from_provider, records[0].to_provider, records[0].outcome) == ("groq", "openai", "rate_limited")


def test_a_single_provider_chain_behaves_like_that_provider() -> None:
    error = _StatusError(429)
    with pytest.raises(_StatusError) as caught:
        FallbackLLMClient([_Fake("groq", error)]).chat(MESSAGES)
    assert caught.value is error


def test_an_empty_chain_is_rejected() -> None:
    with pytest.raises(ValueError):
        FallbackLLMClient([])
