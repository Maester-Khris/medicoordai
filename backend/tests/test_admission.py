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
