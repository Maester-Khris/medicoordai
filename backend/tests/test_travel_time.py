import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from services import travel_time

HERE = (43.6532, -79.3832)
SAME_CELL = (43.6533, -79.3833)   # about 14 m away
FAR_AWAY = (43.7000, -79.3000)
FACILITY = {"id": "f1", "lat": 43.6596, "lng": -79.3884}


@pytest.fixture(autouse=True)
def _clean():
    travel_time.clear()
    yield
    travel_time.clear()


def test_the_estimate_uses_one_speed_per_mode() -> None:
    assert travel_time.estimate_minutes(6.6, "car") == pytest.approx(10.0)
    assert travel_time.estimate_minutes(0.84, "walk") == pytest.approx(10.0)
    assert travel_time.estimate_minutes(3.6, "bus") == pytest.approx(10.0)
    assert travel_time.estimate_minutes(2.52, "bike") == pytest.approx(10.0)


def test_a_remembered_time_is_recalled_for_the_same_cell_facility_and_mode() -> None:
    travel_time.remember(*HERE, "f1", "car", 12, now=0)
    assert travel_time.recall(*SAME_CELL, "f1", "car", now=10) == 12
    assert travel_time.recall(*FAR_AWAY, "f1", "car", now=10) is None
    assert travel_time.recall(*HERE, "f2", "car", now=10) is None
    assert travel_time.recall(*HERE, "f1", "bike", now=10) is None


def test_a_remembered_time_expires() -> None:
    travel_time.remember(*HERE, "f1", "car", 12, now=0)
    assert travel_time.recall(*HERE, "f1", "car", now=travel_time.ENTRY_SECONDS) == 12
    assert travel_time.recall(*HERE, "f1", "car", now=travel_time.ENTRY_SECONDS + 1) is None


def test_travel_minutes_prefers_the_remembered_time_and_falls_back_to_the_estimate() -> None:
    estimate = travel_time.travel_minutes(*HERE, FACILITY, "car", now=0)
    assert 0 < estimate < 5
    travel_time.remember(*HERE, "f1", "car", 9, now=0)
    assert travel_time.travel_minutes(*HERE, FACILITY, "car", now=1) == 9


def test_the_oldest_entries_are_dropped_past_the_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(travel_time, "MAX_ENTRIES", 2)
    travel_time.remember(*HERE, "f1", "car", 1, now=0)
    travel_time.remember(*HERE, "f2", "car", 2, now=0)
    travel_time.remember(*HERE, "f3", "car", 3, now=0)
    assert travel_time.recall(*HERE, "f1", "car", now=0) is None
    assert travel_time.recall(*HERE, "f3", "car", now=0) == 3
