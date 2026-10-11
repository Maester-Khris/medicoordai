import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

import config


@pytest.mark.parametrize("value,expected", [("true", True), ("TRUE", True), ("1", True),
                                            ("false", False), ("", False), ("yes", False)])
def test_demo_mode_reads_env_each_call(monkeypatch: pytest.MonkeyPatch, value: str, expected: bool) -> None:
    monkeypatch.setenv("DEMO_MODE", value)
    assert config.demo_mode() is expected


def test_demo_mode_defaults_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEMO_MODE", raising=False)
    assert config.demo_mode() is False


def test_starter_prompts_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEMO_STARTER_PROMPTS", '["one", "two"]')
    assert config.starter_prompts() == ["one", "two"]


@pytest.mark.parametrize("bad", ["not json", '{"a": 1}', "[]", '[1, 2]', '["ok", ""]'])
def test_starter_prompts_fall_back_on_bad_env(monkeypatch: pytest.MonkeyPatch, bad: str) -> None:
    monkeypatch.setenv("DEMO_STARTER_PROMPTS", bad)
    assert config.starter_prompts() == config.DEFAULT_STARTER_PROMPTS


def test_env_int_returns_the_default_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SOME_SETTING", raising=False)
    assert config.env_int("SOME_SETTING", 7) == 7


def test_env_int_reads_a_valid_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SOME_SETTING", " 42 ")
    assert config.env_int("SOME_SETTING", 7) == 42


@pytest.mark.parametrize("raw", ["abc", "1.5", "0", "-1", "999"])
def test_env_int_falls_back_on_a_malformed_or_out_of_range_value(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, raw: str
) -> None:
    monkeypatch.setenv("SOME_SETTING", raw)
    with caplog.at_level("WARNING"):
        assert config.env_int("SOME_SETTING", 7, minimum=1, maximum=100) == 7
    assert [rec.getMessage() for rec in caplog.records] == ["env_setting_invalid"]


def test_llm_timeout_defaults_to_thirty_seconds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LLM_TIMEOUT_SECONDS", raising=False)
    assert config.llm_timeout_seconds() == 30
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "12")
    assert config.llm_timeout_seconds() == 12


def test_provider_chain_is_empty_when_unset_and_ordered_when_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LLM_PROVIDER_CHAIN", raising=False)
    assert config.llm_provider_chain() == []
    monkeypatch.setenv("LLM_PROVIDER_CHAIN", " Groq, openai ,,anthropic ")
    assert config.llm_provider_chain() == ["groq", "openai", "anthropic"]


@pytest.mark.parametrize("raw, expected", [
    (None, True), ("on", True), ("true", True), ("1", True), ("anything", True),
    ("off", False), ("OFF", False), ("0", False), ("false", False), ("no", False), (" off ", False),
])
def test_load_aware_routing_is_on_unless_switched_off(monkeypatch: pytest.MonkeyPatch, raw, expected) -> None:
    import config

    if raw is None:
        monkeypatch.delenv("LOAD_AWARE_ROUTING", raising=False)
    else:
        monkeypatch.setenv("LOAD_AWARE_ROUTING", raw)
    assert config.load_aware_routing() is expected


def test_one_route_is_requested_up_front_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    import config

    monkeypatch.delenv("ROUTES_UP_FRONT", raising=False)
    assert config.routes_up_front() == 1
    monkeypatch.setenv("ROUTES_UP_FRONT", "3")
    assert config.routes_up_front() == 3
    monkeypatch.setenv("ROUTES_UP_FRONT", "9")
    assert config.routes_up_front() == 1


def test_stubbed_providers_lists_the_overrides_that_are_set(monkeypatch: pytest.MonkeyPatch) -> None:
    import config

    monkeypatch.delenv("GROQ_BASE_URL", raising=False)
    monkeypatch.delenv("GEOAPIFY_BASE_URL", raising=False)
    assert config.stubbed_providers() == []
    monkeypatch.setenv("GEOAPIFY_BASE_URL", "http://mock:9000")
    assert config.stubbed_providers() == ["geoapify"]
    monkeypatch.setenv("GROQ_BASE_URL", "http://mock:9000")
    assert config.stubbed_providers() == ["groq", "geoapify"]
    monkeypatch.setenv("GROQ_BASE_URL", "   ")
    assert config.stubbed_providers() == ["geoapify"]
