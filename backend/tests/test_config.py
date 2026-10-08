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
