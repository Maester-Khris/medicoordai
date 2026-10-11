import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import patch

import pytest

from services import facility_load, travel_time
from services.recommendation import rank_facilities, score_minutes
from services.wait_cache import WaitSnapshot

HERE = (43.6532, -79.3832)
# NEAR is about 0.8 km away, MID about 3.3 km, FAR about 7.7 km: 1.2, 5.0 and 11.7 minutes by car.
NEAR = {"id": "near", "name": "Near", "category": "hospital", "lat": 43.6596, "lng": -79.3884, "distanceKm": 0.82}
MID = {"id": "mid", "name": "Mid", "category": "ambulatory", "lat": 43.6800, "lng": -79.4000, "distanceKm": 3.27}
FAR = {"id": "far", "name": "Far", "category": "hospital", "lat": 43.7224, "lng": -79.3763, "distanceKm": 7.71}


def _wait(**minutes: int) -> WaitSnapshot:
    wait_map = {fid: {"wait_minutes": m, "raw_wait": None, "predicted": False} for fid, m in minutes.items()}
    return WaitSnapshot(wait_map, "v", None)


@pytest.fixture(autouse=True)
def _on(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LOAD_AWARE_ROUTING", "on")
    monkeypatch.setenv("LOAD_SCORE_TIE_MINUTES", "0")
    travel_time.clear()
    facility_load.reset_for_tests()
    yield
    travel_time.clear()
    facility_load.reset_for_tests()


def _rank(candidates: list[dict], severity: str, wait: WaitSnapshot = _wait(), rng=lambda: 0.0) -> list[str]:
    with patch("services.recommendation.current_wait", return_value=wait):
        return [f["id"] for f in rank_facilities(candidates, severity, *HERE, rng=rng)]


def test_with_nothing_else_known_the_nearest_is_recommended() -> None:
    assert _rank([NEAR, MID, FAR], "routine") == ["near", "mid", "far"]


def test_a_long_posted_wait_moves_the_recommendation() -> None:
    assert _rank([NEAR, MID, FAR], "moderate", _wait(near=60, mid=5)) == ["mid", "far", "near"]


def test_a_facility_without_wait_data_counts_as_no_wait() -> None:
    assert _rank([NEAR, MID], "routine", _wait(mid=0)) == ["near", "mid"]


def test_recent_assignments_move_the_recommendation() -> None:
    with patch("services.recommendation.facility_load.recent_assignments",
               side_effect=lambda fid: 10 if fid == "near" else 0):
        assert _rank([NEAR, MID, FAR], "routine") == ["mid", "far", "near"]


def test_a_remembered_road_time_replaces_the_estimate() -> None:
    travel_time.remember(*HERE, "near", "car", 30)
    assert _rank([NEAR, MID], "routine") == ["mid", "near"]


@pytest.mark.parametrize("severity", ["urgent", "emergent"])
def test_urgent_and_emergent_ignore_waits_and_load(severity: str) -> None:
    with patch("services.recommendation.facility_load.recent_assignments", return_value=50):
        assert _rank([NEAR, MID, FAR], severity, _wait(near=600)) == ["near", "mid", "far"]


def test_switched_off_it_is_nearest_first(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOAD_AWARE_ROUTING", "off")
    assert _rank([NEAR, MID, FAR], "routine", _wait(near=600)) == ["near", "mid", "far"]


def test_close_scores_are_a_tie_and_the_pick_among_them_is_random(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOAD_SCORE_TIE_MINUTES", "5")
    assert _rank([NEAR, MID, FAR], "routine", rng=lambda: 0.0) == ["near", "mid", "far"]
    assert _rank([NEAR, MID, FAR], "routine", rng=lambda: 0.99) == ["mid", "near", "far"]


def test_a_candidate_outside_the_tie_band_is_never_picked(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOAD_SCORE_TIE_MINUTES", "5")
    for value in (0.0, 0.34, 0.67, 0.999):
        assert _rank([NEAR, MID, FAR], "routine", rng=lambda v=value: v)[0] != "far"


def test_one_candidate_or_none_is_returned_as_is() -> None:
    assert _rank([NEAR], "routine") == ["near"]
    assert _rank([], "routine") == []


def test_the_score_is_travel_plus_wait_plus_the_load_penalty() -> None:
    wait_map = {"mid": {"wait_minutes": 20}}
    with patch("services.recommendation.facility_load.recent_assignments", return_value=3):
        score = score_minutes(MID, *HERE, wait_map)
    travel = travel_time.travel_minutes(*HERE, MID, "car")
    assert score == pytest.approx(travel + 20 + 3 * 4.0)  # 4 minutes per recent guest for "ambulatory"
