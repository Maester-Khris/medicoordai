import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

import logging
from unittest.mock import patch

import pytest

from llm.anthropic_client import AnthropicClient
from llm.fallback import FallbackLLMClient
from llm.groq_client import GroqClient
from llm.instrumented import InstrumentedLLMClient
from llm.openai_client import OpenAIClient
from services.llm_agent import get_llm_client


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch):
    for name, value in {"GROQ_API_KEY": "g", "OPENAI_API_KEY": "o", "OPENAI_MODEL": "m", "ANTHROPIC_API_KEY": "a"}.items():
        monkeypatch.setenv(name, value)
    for name in ("LLM_PROVIDER", "LLM_PROVIDER_CHAIN", "LLM_TIMEOUT_SECONDS"):
        monkeypatch.delenv(name, raising=False)
    with patch("llm.groq_client.Groq") as groq, patch("llm.openai_client.OpenAI") as openai, \
         patch("llm.anthropic_client.anthropic.Anthropic") as anthropic:
        yield {"groq": groq, "openai": openai, "anthropic": anthropic}


def _providers(client: FallbackLLMClient) -> list[tuple[str, type]]:
    return [(c.provider, type(c._inner)) for c in client._clients]  # type: ignore[attr-defined]


def test_without_a_chain_the_default_is_one_instrumented_groq_client_with_sdk_retries(_env) -> None:
    client = get_llm_client()
    assert isinstance(client, InstrumentedLLMClient) and client.provider == "groq"
    assert isinstance(client._inner, GroqClient)
    assert _env["groq"].call_args.kwargs == {"api_key": "g", "timeout": 30}


@pytest.mark.parametrize("name,expected", [("anthropic", AnthropicClient), ("openai", OpenAIClient),
                                           ("GROQ", GroqClient), ("something-else", GroqClient)])
def test_llm_provider_still_selects_the_single_client(monkeypatch: pytest.MonkeyPatch, name: str, expected: type) -> None:
    monkeypatch.setenv("LLM_PROVIDER", name)
    client = get_llm_client()
    assert isinstance(client, InstrumentedLLMClient) and isinstance(client._inner, expected)


def test_a_chain_builds_the_providers_in_order_with_sdk_retries_off(monkeypatch: pytest.MonkeyPatch, _env) -> None:
    monkeypatch.setenv("LLM_PROVIDER_CHAIN", "groq,openai,anthropic")
    client = get_llm_client()
    assert isinstance(client, FallbackLLMClient)
    assert _providers(client) == [("groq", GroqClient), ("openai", OpenAIClient), ("anthropic", AnthropicClient)]
    for sdk in _env.values():
        assert sdk.call_args.kwargs["max_retries"] == 0 and sdk.call_args.kwargs["timeout"] == 30


def test_the_chain_wins_over_llm_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("LLM_PROVIDER_CHAIN", "openai,groq")
    assert _providers(get_llm_client()) == [("openai", OpenAIClient), ("groq", GroqClient)]  # type: ignore[arg-type]


def test_unknown_names_and_providers_without_a_key_are_skipped_with_a_warning(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("LLM_PROVIDER_CHAIN", "groq,mistral,openai,anthropic")
    monkeypatch.delenv("OPENAI_MODEL")
    with caplog.at_level(logging.WARNING):
        client = get_llm_client()
    assert _providers(client) == [("groq", GroqClient), ("anthropic", AnthropicClient)]  # type: ignore[arg-type]
    skipped = [(r.provider, r.reason) for r in caplog.records if r.getMessage() == "llm_provider_skipped"]
    assert skipped == [("mistral", "unknown provider"), ("openai", "OPENAI_MODEL is not set")]


def test_a_chain_with_no_usable_provider_is_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER_CHAIN", "mistral,openai")
    monkeypatch.delenv("OPENAI_API_KEY")
    with pytest.raises(RuntimeError, match="no usable provider"):
        get_llm_client()


def test_groq_and_anthropic_clients_take_the_timeout_from_the_environment(monkeypatch: pytest.MonkeyPatch, _env) -> None:
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "9")
    GroqClient()
    AnthropicClient(max_retries=0)
    assert _env["groq"].call_args.kwargs == {"api_key": "g", "timeout": 9}
    assert _env["anthropic"].call_args.kwargs == {"api_key": "a", "timeout": 9, "max_retries": 0}


def test_anthropic_defaults_to_the_current_haiku_and_never_sends_temperature(monkeypatch: pytest.MonkeyPatch, _env) -> None:
    from unittest.mock import MagicMock

    from llm.base import LLMMessage

    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    client = AnthropicClient()
    assert client.model_name == "claude-haiku-5-5"

    create = _env["anthropic"].return_value.messages.create
    create.return_value = MagicMock(
        content=[MagicMock(type="thinking"), MagicMock(type="text", text="ok")],
        usage=MagicMock(input_tokens=3, output_tokens=2),
    )
    response = client.chat(messages=[LLMMessage(role="user", content="hi")], temperature=0.2)

    sent = create.call_args.kwargs
    assert "temperature" not in sent and sent["max_tokens"] == 4096 and sent["model"] == "claude-haiku-5-5"
    assert response.content == "ok"  # a leading thinking block is skipped, not read as the answer
