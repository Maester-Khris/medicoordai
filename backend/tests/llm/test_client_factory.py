import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

import logging
from unittest.mock import ANY, AsyncMock, patch

import pytest

from llm.anthropic_client import AnthropicClient
from llm.base import BaseLLMClient, LLMMessage, LLMResponse
from llm.breaker import CircuitBreakerLLMClient, ProviderCircuitOpen
from llm.fallback import FallbackLLMClient
from llm.groq_client import GroqClient
from llm.instrumented import InstrumentedLLMClient
from llm.openai_client import OpenAIClient
from llm.retry import RetryingLLMClient
from services import llm_agent
from services.llm_agent import build_guarded_client, get_llm_client


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch):
    for name, value in {"GROQ_API_KEY": "g", "OPENAI_API_KEY": "o", "OPENAI_MODEL": "m", "ANTHROPIC_API_KEY": "a"}.items():
        monkeypatch.setenv(name, value)
    for name in ("LLM_PROVIDER", "LLM_PROVIDER_CHAIN", "LLM_TIMEOUT_SECONDS"):
        monkeypatch.delenv(name, raising=False)
    with patch("llm.groq_client.AsyncGroq") as groq, patch("llm.openai_client.AsyncOpenAI") as openai, \
         patch("llm.anthropic_client.anthropic.AsyncAnthropic") as anthropic:
        yield {"groq": groq, "openai": openai, "anthropic": anthropic}


def _unwrap(client: BaseLLMClient) -> BaseLLMClient:
    """The provider client under Instrumented, Breaker and Retrying."""
    while hasattr(client, "_inner"):
        client = client._inner  # type: ignore[attr-defined]
    return client


def _providers(client: FallbackLLMClient) -> list[tuple[str, type]]:
    return [(c.provider, type(_unwrap(c))) for c in client._clients]  # type: ignore[attr-defined]


def test_without_a_chain_the_default_is_one_guarded_groq_client_with_sdk_retries_off(_env) -> None:
    client = get_llm_client()
    assert isinstance(client, InstrumentedLLMClient) and client.provider == "groq"
    assert isinstance(_unwrap(client), GroqClient)
    assert _env["groq"].call_args.kwargs == {"api_key": "g", "timeout": 30, "http_client": ANY, "max_retries": 0}


def test_the_stack_is_instrumented_then_breaker_then_retry_then_the_provider_client() -> None:
    outer = build_guarded_client("groq", breaker=True)
    layers = [type(outer)]
    while hasattr(outer, "_inner"):
        outer = outer._inner  # type: ignore[attr-defined]
        layers.append(type(outer))
    assert layers == [InstrumentedLLMClient, CircuitBreakerLLMClient, RetryingLLMClient, GroqClient]


def test_without_the_breaker_the_stack_is_instrumented_then_retry_then_the_provider_client() -> None:
    outer = build_guarded_client("groq", breaker=False)
    assert isinstance(outer, InstrumentedLLMClient)
    assert isinstance(outer._inner, RetryingLLMClient) and isinstance(outer._inner._inner, GroqClient)  # type: ignore[attr-defined]


def test_the_guard_settings_reach_the_stack(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_RETRY_ATTEMPTS", "3")
    monkeypatch.setenv("LLM_BREAKER_FAILURES", "7")
    monkeypatch.setenv("LLM_BREAKER_COOLDOWN_SECONDS", "45")
    breaker = build_guarded_client("groq", breaker=True)._inner  # type: ignore[attr-defined]
    assert (breaker._failure_threshold, breaker._cooldown_seconds) == (7, 45)
    assert breaker._inner.attempts == 3


class _Down(BaseLLMClient):
    def __init__(self) -> None:
        self.calls = 0

    @property
    def model_name(self) -> str:
        return "down"

    async def chat(self, messages, tools=None, temperature=0.2, stop=None, force_tool=None) -> LLMResponse:
        self.calls += 1
        error = Exception("unavailable")
        error.status_code = 503  # type: ignore[attr-defined]
        raise error


class _Up(_Down):
    async def chat(self, messages, tools=None, temperature=0.2, stop=None, force_tool=None) -> LLMResponse:
        self.calls += 1
        return LLMResponse(content="from anthropic", tool_calls=None, finish_reason="stop", model="up",
                           usage={"prompt_tokens": 1, "completion_tokens": 1})


def test_a_failing_provider_is_skipped_once_its_breaker_opens_and_the_next_provider_answers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_BREAKER_FAILURES", "2")
    monkeypatch.setenv("LLM_RETRY_ATTEMPTS", "1")
    groq, anthropic = _Down(), _Up()
    fakes = {"groq": groq, "anthropic": anthropic}
    with patch.object(llm_agent, "_build_provider_client", side_effect=lambda provider, retries: fakes[provider]):
        chain = FallbackLLMClient([build_guarded_client("groq", breaker=True),
                                   build_guarded_client("anthropic", breaker=True)])
    messages = [LLMMessage(role="user", content="hi")]
    for _ in range(4):
        assert asyncio.run(chain.chat(messages)).content == "from anthropic"
    assert groq.calls == 2  # opened after two failures; the other two calls never reached it
    assert anthropic.calls == 4


def test_a_single_provider_with_an_open_breaker_fails_at_once(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_BREAKER_FAILURES", "2")
    monkeypatch.setenv("LLM_RETRY_ATTEMPTS", "1")
    groq = _Down()
    with patch.object(llm_agent, "_build_provider_client", return_value=groq):
        client = build_guarded_client("groq", breaker=True)
    messages = [LLMMessage(role="user", content="hi")]
    for _ in range(2):
        with pytest.raises(Exception, match="unavailable"):
            asyncio.run(client.chat(messages))
    with pytest.raises(ProviderCircuitOpen):
        asyncio.run(client.chat(messages))
    assert groq.calls == 2


@pytest.mark.parametrize("name,expected", [("anthropic", AnthropicClient), ("openai", OpenAIClient),
                                           ("GROQ", GroqClient), ("something-else", GroqClient)])
def test_llm_provider_still_selects_the_single_client(monkeypatch: pytest.MonkeyPatch, name: str, expected: type) -> None:
    monkeypatch.setenv("LLM_PROVIDER", name)
    client = get_llm_client()
    assert isinstance(client, InstrumentedLLMClient) and isinstance(_unwrap(client), expected)


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
    assert _env["groq"].call_args.kwargs == {"api_key": "g", "timeout": 9, "http_client": ANY}
    assert _env["anthropic"].call_args.kwargs == {"api_key": "a", "timeout": 9, "max_retries": 0, "http_client": ANY}


def test_anthropic_defaults_to_the_current_haiku_and_never_sends_temperature(monkeypatch: pytest.MonkeyPatch, _env) -> None:
    from unittest.mock import MagicMock

    from llm.base import LLMMessage

    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    client = AnthropicClient()
    assert client.model_name == "claude-haiku-5-5"

    create = AsyncMock(return_value=MagicMock(
        content=[MagicMock(type="thinking"), MagicMock(type="text", text="ok")],
        usage=MagicMock(input_tokens=3, output_tokens=2),
    ))
    _env["anthropic"].return_value.messages.create = create
    response = asyncio.run(client.chat(messages=[LLMMessage(role="user", content="hi")], temperature=0.2))

    sent = create.call_args.kwargs
    assert "temperature" not in sent and sent["max_tokens"] == 4096 and sent["model"] == "claude-haiku-5-5"
    assert response.content == "ok"  # a leading thinking block is skipped, not read as the answer
