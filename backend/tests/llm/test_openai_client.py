import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from unittest.mock import MagicMock, patch

import pytest

from llm.base import LLMMessage
from llm.tools import TRIAGE_RESPONSE


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_MODEL", "test-model")
    monkeypatch.delenv("LLM_TIMEOUT_SECONDS", raising=False)


def _completion(content: str | None = "hello", tool_calls: list | None = None, finish_reason: str = "stop"):
    return MagicMock(
        choices=[MagicMock(finish_reason=finish_reason, message=MagicMock(content=content, tool_calls=tool_calls))],
        usage=MagicMock(prompt_tokens=21, completion_tokens=8),
    )


def _tool_call():
    function = MagicMock(arguments='{"severity": "urgent"}')
    function.name = "triage_response"  # MagicMock(name=...) sets repr, not the attribute
    return MagicMock(id="tc1", function=function)


def _client(completion=None):
    from llm.openai_client import OpenAIClient

    with patch("llm.openai_client.OpenAI") as sdk:
        sdk.return_value.chat.completions.create.return_value = completion or _completion()
        client = OpenAIClient()
    return client, sdk


def test_plain_text_request_and_response() -> None:
    client, sdk = _client()
    resp = client.chat(messages=[LLMMessage(role="system", content="be brief"), LLMMessage(role="user", content="hi")])

    sent = sdk.return_value.chat.completions.create.call_args.kwargs
    assert sent == {
        "model": "test-model",
        "messages": [{"role": "system", "content": "be brief"}, {"role": "user", "content": "hi"}],
        "temperature": 0.2,
    }
    assert (resp.content, resp.tool_calls, resp.finish_reason, resp.model) == ("hello", None, "stop", "test-model")
    assert resp.usage == {"prompt_tokens": 21, "completion_tokens": 8}


def test_tools_are_sent_with_auto_choice_and_stop_sequences() -> None:
    client, sdk = _client()
    client.chat(messages=[LLMMessage(role="user", content="hi")], tools=[TRIAGE_RESPONSE], stop=["END"], temperature=0.0)

    sent = sdk.return_value.chat.completions.create.call_args.kwargs
    assert sent["tool_choice"] == "auto" and sent["stop"] == ["END"] and sent["temperature"] == 0.0
    function = sent["tools"][0]["function"]
    assert sent["tools"][0]["type"] == "function" and function["name"] == TRIAGE_RESPONSE.name
    assert function["parameters"] == {
        "type": "object", "properties": TRIAGE_RESPONSE.parameters, "required": TRIAGE_RESPONSE.required,
    }


def test_a_forced_tool_is_named_in_tool_choice() -> None:
    client, sdk = _client()
    client.chat(messages=[LLMMessage(role="user", content="hi")], tools=[TRIAGE_RESPONSE], force_tool="triage_response")
    sent = sdk.return_value.chat.completions.create.call_args.kwargs
    assert sent["tool_choice"] == {"type": "function", "function": {"name": "triage_response"}}


def test_tool_calls_are_read_even_when_finish_reason_is_stop() -> None:
    # OpenAI reports "stop" for a forced tool call; the call itself is the signal.
    client, _ = _client(_completion(content=None, tool_calls=[_tool_call()], finish_reason="stop"))
    resp = client.chat(messages=[LLMMessage(role="user", content="hi")], tools=[TRIAGE_RESPONSE])
    assert resp.tool_calls == [{"id": "tc1", "name": "triage_response", "arguments": '{"severity": "urgent"}'}]
    assert resp.content is None


def test_tool_result_messages_keep_their_call_id_and_name() -> None:
    client, sdk = _client()
    client.chat(messages=[LLMMessage(role="tool", content="{}", tool_call_id="tc1", name="triage_response")])
    assert sdk.return_value.chat.completions.create.call_args.kwargs["messages"] == [
        {"role": "tool", "content": "{}", "tool_call_id": "tc1", "name": "triage_response"}
    ]


def test_the_sdk_gets_the_timeout_and_keeps_its_own_retries_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "12")
    _, sdk = _client()
    assert sdk.call_args.kwargs == {"api_key": "test-key", "timeout": 12}


def test_retries_can_be_turned_off_for_a_fallback_chain() -> None:
    from llm.openai_client import OpenAIClient

    with patch("llm.openai_client.OpenAI") as sdk:
        OpenAIClient(max_retries=0)
    assert sdk.call_args.kwargs == {"api_key": "test-key", "timeout": 30, "max_retries": 0}


@pytest.mark.parametrize("missing", ["OPENAI_API_KEY", "OPENAI_MODEL"])
def test_a_missing_key_or_model_is_refused(monkeypatch: pytest.MonkeyPatch, missing: str) -> None:
    from llm.openai_client import OpenAIClient

    monkeypatch.delenv(missing)
    with patch("llm.openai_client.OpenAI"), pytest.raises(RuntimeError, match=missing):
        OpenAIClient()


def test_a_provider_error_is_not_swallowed() -> None:
    client, sdk = _client()
    sdk.return_value.chat.completions.create.side_effect = RuntimeError("boom")
    with pytest.raises(RuntimeError, match="boom"):
        client.chat(messages=[LLMMessage(role="user", content="hi")])
