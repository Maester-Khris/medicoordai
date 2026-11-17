import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from observability import _registry
from services import admission


@pytest.fixture(autouse=True)
def _clean(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("MAX_TURNS_IN_FLIGHT", raising=False)
    monkeypatch.delenv("ADMISSION_RETRY_SECONDS", raising=False)
    admission.reset_for_tests()
    yield
    admission.reset_for_tests()


def test_without_a_limit_every_turn_is_admitted() -> None:
    with admission.admit():
        with admission.admit():
            assert admission.in_flight() == 2
    assert admission.in_flight() == 0


def test_at_the_limit_the_next_turn_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAX_TURNS_IN_FLIGHT", "1")
    with admission.admit():
        with pytest.raises(admission.Busy):
            with admission.admit():
                pass
        assert admission.in_flight() == 1
    assert admission.in_flight() == 0


def test_a_turn_that_raises_still_frees_its_slot(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAX_TURNS_IN_FLIGHT", "1")
    with pytest.raises(ValueError):
        with admission.admit():
            raise ValueError("turn failed")
    with admission.admit():
        assert admission.in_flight() == 1


def test_a_refused_turn_is_counted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAX_TURNS_IN_FLIGHT", "1")
    before = _registry.get_sample_value("chat_turns_rejected_total") or 0
    with admission.admit():
        with pytest.raises(admission.Busy):
            with admission.admit():
                pass
    assert _registry.get_sample_value("chat_turns_rejected_total") == before + 1


def test_the_gauge_reads_the_turns_in_flight() -> None:
    with admission.admit():
        assert _registry.get_sample_value("chat_turns_in_flight") == 1
    assert _registry.get_sample_value("chat_turns_in_flight") == 0


def test_a_bad_limit_means_no_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAX_TURNS_IN_FLIGHT", "many")
    with admission.admit():
        with admission.admit():
            assert admission.in_flight() == 2


def test_the_retry_delay_is_the_setting_plus_up_to_two_seconds(monkeypatch: pytest.MonkeyPatch) -> None:
    assert admission.retry_after_seconds(lambda: 0.0) == 3
    assert admission.retry_after_seconds(lambda: 0.999) == 5
    monkeypatch.setenv("ADMISSION_RETRY_SECONDS", "7")
    assert admission.retry_after_seconds(lambda: 0.0) == 7


def test_a_limit_with_admission_control_off_is_ignored_and_nothing_is_counted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAX_TURNS_IN_FLIGHT", "1")
    monkeypatch.setenv("ADMISSION_CONTROL", "off")
    before = _registry.get_sample_value("chat_turns_rejected_total") or 0
    with admission.admit():
        with admission.admit():
            assert admission.in_flight() == 2
    assert (_registry.get_sample_value("chat_turns_rejected_total") or 0) == before


def test_a_limit_with_admission_control_on_still_refuses(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAX_TURNS_IN_FLIGHT", "1")
    monkeypatch.setenv("ADMISSION_CONTROL", "on")
    with admission.admit():
        with pytest.raises(admission.Busy):
            with admission.admit():
                pass


def test_a_zero_limit_still_means_no_limit_with_admission_control_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAX_TURNS_IN_FLIGHT", "0")
    monkeypatch.setenv("ADMISSION_CONTROL", "on")
    with admission.admit():
        with admission.admit():
            with admission.admit():
                assert admission.in_flight() == 3


def test_an_unknown_admission_control_value_behaves_as_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAX_TURNS_IN_FLIGHT", "1")
    monkeypatch.setenv("ADMISSION_CONTROL", "maybe")
    with admission.admit():
        with pytest.raises(admission.Busy):
            with admission.admit():
                pass


@pytest.mark.parametrize("raw,expected", [(None, True), ("on", True), ("ON", True), ("off", False), (" OFF ", False), ("maybe", True), ("", True)])
def test_admission_control_enabled_reads_the_environment(monkeypatch: pytest.MonkeyPatch, raw: str | None, expected: bool) -> None:
    import config
    if raw is None:
        monkeypatch.delenv("ADMISSION_CONTROL", raising=False)
    else:
        monkeypatch.setenv("ADMISSION_CONTROL", raw)
    assert config.admission_control_enabled() is expected
