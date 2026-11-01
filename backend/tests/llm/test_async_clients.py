import asyncio
import inspect
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from unittest.mock import patch

import httpx
import pytest

from llm.limits import connection_limits
from llm.sync import run_sync


@pytest.fixture(autouse=True)
def _keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "g")
    monkeypatch.setenv("OPENAI_API_KEY", "o")
    monkeypatch.setenv("OPENAI_MODEL", "test-model")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "a")
    monkeypatch.delenv("LLM_MAX_CONNECTIONS", raising=False)


def test_every_client_chat_is_a_coroutine_function() -> None:
    from llm.anthropic_client import AnthropicClient
    from llm.base import BaseLLMClient
    from llm.fallback import FallbackLLMClient
    from llm.groq_client import GroqClient
    from llm.instrumented import InstrumentedLLMClient
    from llm.openai_client import OpenAIClient

    for cls in (BaseLLMClient, GroqClient, OpenAIClient, AnthropicClient, FallbackLLMClient, InstrumentedLLMClient):
        assert inspect.iscoroutinefunction(cls.chat), cls.__name__


def test_connection_limits_default_to_2000() -> None:
    limits = connection_limits()
    assert limits.max_connections == 2000 and limits.max_keepalive_connections == 2000


def test_connection_limits_come_from_the_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_MAX_CONNECTIONS", "1234")
    assert connection_limits().max_connections == 1234


def test_a_bad_connection_setting_falls_back_to_the_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_MAX_CONNECTIONS", "plenty")
    assert connection_limits().max_connections == 2000


@pytest.mark.parametrize("module, sdk_name, client_name", [
    ("llm.groq_client", "AsyncGroq", "GroqClient"),
    ("llm.openai_client", "AsyncOpenAI", "OpenAIClient"),
])
def test_each_sdk_client_is_async_and_given_an_explicit_http_client(module: str, sdk_name: str, client_name: str) -> None:
    import importlib

    with patch(f"{module}.{sdk_name}") as sdk:
        getattr(importlib.import_module(module), client_name)()
    assert isinstance(sdk.call_args.kwargs["http_client"], httpx.AsyncClient)


def test_the_anthropic_client_is_async_and_given_an_explicit_http_client() -> None:
    from llm.anthropic_client import AnthropicClient

    with patch("llm.anthropic_client.anthropic.AsyncAnthropic") as sdk:
        AnthropicClient()
    assert isinstance(sdk.call_args.kwargs["http_client"], httpx.AsyncClient)


def test_run_sync_returns_the_result_and_reuses_one_loop() -> None:
    async def loop_id() -> int:
        return id(asyncio.get_running_loop())

    assert run_sync(loop_id()) == run_sync(loop_id())


def test_run_sync_lets_the_exception_through() -> None:
    async def boom() -> None:
        raise ValueError("boom")

    with pytest.raises(ValueError, match="boom"):
        run_sync(boom())
