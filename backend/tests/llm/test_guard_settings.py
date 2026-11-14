import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

import pytest

import config


@pytest.mark.parametrize("getter,setting,default,custom", [
    (config.llm_retry_attempts, "LLM_RETRY_ATTEMPTS", 2, "3"),
    (config.llm_breaker_failures, "LLM_BREAKER_FAILURES", 5, "8"),
    (config.llm_breaker_cooldown_seconds, "LLM_BREAKER_COOLDOWN_SECONDS", 30, "60"),
    (config.llm_conversation_token_cap, "LLM_CONVERSATION_TOKEN_CAP", 30000, "12345"),
])
def test_guard_settings_default_read_the_environment_and_survive_a_bad_value(
    monkeypatch: pytest.MonkeyPatch, getter, setting: str, default: int, custom: str
) -> None:
    monkeypatch.delenv(setting, raising=False)
    assert getter() == default
    monkeypatch.setenv(setting, custom)
    assert getter() == int(custom)
    monkeypatch.setenv(setting, "not a number")
    assert getter() == default
    monkeypatch.setenv(setting, "0")
    assert getter() == default


def test_the_retry_attempts_have_a_ceiling_so_a_typo_cannot_multiply_provider_traffic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_RETRY_ATTEMPTS", "5")
    assert config.llm_retry_attempts() == 5
    monkeypatch.setenv("LLM_RETRY_ATTEMPTS", "50")
    assert config.llm_retry_attempts() == 2
