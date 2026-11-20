import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

import pytest

import config


@pytest.mark.parametrize("getter,setting,default,custom", [
    (config.llm_retry_attempts, "LLM_RETRY_ATTEMPTS", 2, "3"),
    (config.llm_breaker_failures, "LLM_BREAKER_FAILURES", 5, "8"),
    (config.llm_breaker_cooldown_seconds, "LLM_BREAKER_COOLDOWN_SECONDS", 30, "60"),
    (config.llm_conversation_token_cap, "LLM_CONVERSATION_TOKEN_CAP", 22000, "12345"),
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


GUARD_READERS = [
    (config.red_flag_floor_mode, "RED_FLAG_FLOOR_MODE", "shadow"),
    (config.emergency_mismatch_mode, "EMERGENCY_MISMATCH_MODE", "shadow"),
    (config.groundedness_guard_mode, "GROUNDEDNESS_GUARD_MODE", "enforce"),
]


@pytest.mark.parametrize("reader,setting,default", GUARD_READERS)
def test_guard_mode_defaults_when_unset(monkeypatch: pytest.MonkeyPatch, reader, setting: str, default: str) -> None:
    monkeypatch.delenv(setting, raising=False)
    assert reader() == default


@pytest.mark.parametrize("reader,setting,default", GUARD_READERS)
def test_guard_mode_accepts_each_valid_value_case_insensitively_and_padded(
    monkeypatch: pytest.MonkeyPatch, reader, setting: str, default: str
) -> None:
    for raw, expected in [(" ENFORCE ", "enforce"), ("off", "off"), ("Shadow", "shadow")]:
        monkeypatch.setenv(setting, raw)
        assert reader() == expected


@pytest.mark.parametrize("reader,setting,default", GUARD_READERS)
@pytest.mark.parametrize("bad", ["on", "", "enforcee"])
def test_guard_mode_falls_back_to_the_guard_default_and_warns_on_a_bad_value(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, reader, setting: str, default: str, bad: str
) -> None:
    monkeypatch.setenv(setting, bad)
    with caplog.at_level("WARNING"):
        assert reader() == default
    warnings = [r for r in caplog.records if r.message == "env_setting_invalid"]
    if bad == "":
        assert warnings == []  # an empty value counts as unset
    else:
        assert len(warnings) == 1 and warnings[0].setting == setting
