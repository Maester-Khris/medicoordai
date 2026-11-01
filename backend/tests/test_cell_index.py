import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import patch

import pytest

from services import cell_index, proximity
from services.proximity import DRIVE_MPS, TRANSIT_MPS, WALK_MPS, haversine_km

TORONTO = (43.6532, -79.3832)
OTTAWA = (45.4215, -75.6972)
SEVERITIES = ("routine", "moderate", "urgent", "emergent")
CATEGORIES = ("hospital", "ambulatory", "residential")


@pytest.fixture(autouse=True)
def _always_indexed(monkeypatch: pytest.MonkeyPatch) -> None:
    """These tests are about the index: use it whatever the size of the list."""
    monkeypatch.setattr(cell_index, "MIN_INDEXED", 0)


def _facilities(count: int, seed: int, spread: float = 0.25) -> list[dict]:
    rng = random.Random(seed)
    return [
        {
            "id": f"f{i}", "name": f"Facility {i}", "category": rng.choice(CATEGORIES),
            "address": f"{i} Main St", "phone": None,
            "lat": TORONTO[0] + rng.uniform(-spread, spread),
            "lng": TORONTO[1] + rng.uniform(-spread, spread),
            "accepted_severity": rng.sample(SEVERITIES, rng.randint(1, 4)),
        }
        for i in range(count)
    ]


def _scan_nearest(facilities: list[dict], lat: float, lng: float, severity: str, top_n: int) -> list[dict]:
    """The lookup as it was before the index: every facility, then a stable sort by distance."""
    eligible = [f for f in facilities if severity in f.get("accepted_severity", [])]
    ranked = sorted(
        [{**f, "distanceKm": round(haversine_km(lat, lng, f["lat"], f["lng"]), 2)} for f in eligible],
        key=lambda x: x["distanceKm"],
    )
    return ranked[:top_n]


def _scan_within(facilities: list[dict], lat: float, lng: float, radius_m: int, category: str | None) -> list[dict]:
    """find_facilities_within as it was before the index."""
    radius = min(radius_m, proximity.MAX_RADIUS_M)
    rows: list[dict] = []
    for f in facilities:
        if category is not None and f.get("category") != category:
            continue
        distance_m = round(haversine_km(lat, lng, f["lat"], f["lng"]) * 1000)
        if distance_m > radius:
            continue
        rows.append({
            "facility_id": str(f["id"]), "facility_name": f["name"], "category": f["category"],
            "address": f.get("address") or "", "phone": f.get("phone"), "is_operational": True,
            "distance_m": distance_m,
            "eta_walk_min": round(distance_m / WALK_MPS / 60),
            "eta_transit_min": round(distance_m / TRANSIT_MPS / 60),
            "eta_drive_min": round(distance_m / DRIVE_MPS / 60),
        })
    rows.sort(key=lambda row: row["distance_m"])
    return rows[:proximity.NEARBY_LIMIT]


def _nearest(facilities: list[dict] | None, lat: float, lng: float, severity: str, top_n: int = 3):
    with patch("services.proximity.get_cached_facilities", return_value=(facilities, '"v"')):
        return proximity.find_nearest_facilities(lat, lng, severity, top_n)


def _within(facilities: list[dict], lat: float, lng: float, radius_m: int, category: str | None):
    with patch("services.proximity.get_cached_facilities", return_value=(facilities, '"v"')):
        return proximity.find_facilities_within(lat, lng, radius_m, category)


@pytest.mark.parametrize("count, seed", [(304, 1), (3000, 2)])
def test_the_index_gives_exactly_the_answer_of_the_scan(count: int, seed: int) -> None:
    facilities = _facilities(count, seed)
    rng = random.Random(seed + 100)
    for _ in range(200):
        lat = TORONTO[0] + rng.uniform(-0.3, 0.3)
        lng = TORONTO[1] + rng.uniform(-0.3, 0.3)
        severity = rng.choice(SEVERITIES)
        top_n = rng.choice([1, 3, 5])
        assert _nearest(facilities, lat, lng, severity, top_n) == _scan_nearest(facilities, lat, lng, severity, top_n)


def test_a_guest_far_from_every_facility_gets_the_same_answer_as_the_scan() -> None:
    facilities = _facilities(304, 3)
    result = _nearest(facilities, *OTTAWA, "urgent")
    assert result == _scan_nearest(facilities, *OTTAWA, "urgent", 3)
    assert len(result) == 3


def test_a_severity_few_facilities_accept_is_still_found() -> None:
    facilities = _facilities(304, 4)
    for facility in facilities:
        facility["accepted_severity"] = ["routine"]
    facilities[17]["accepted_severity"] = ["emergent"]
    facilities[250]["accepted_severity"] = ["emergent"]
    result = _nearest(facilities, *TORONTO, "emergent")
    assert result == _scan_nearest(facilities, *TORONTO, "emergent", 3)
    assert {f["id"] for f in result} == {"f17", "f250"}


def test_no_facility_accepting_the_severity_is_an_empty_list() -> None:
    facilities = _facilities(50, 5)
    for facility in facilities:
        facility["accepted_severity"] = ["routine"]
    assert _nearest(facilities, *TORONTO, "emergent") == []


def test_an_empty_list_is_empty_and_no_list_is_none() -> None:
    assert _nearest([], *TORONTO, "urgent") == []
    assert _nearest(None, *TORONTO, "urgent") is None


@pytest.mark.parametrize("radius_m", [500, 5000, 20000, 60000])
def test_facilities_within_a_radius_match_the_scan(radius_m: int) -> None:
    facilities = _facilities(304, 6)
    rng = random.Random(radius_m)
    for _ in range(50):
        lat = TORONTO[0] + rng.uniform(-0.3, 0.3)
        lng = TORONTO[1] + rng.uniform(-0.3, 0.3)
        category = rng.choice([None, "hospital"])
        assert _within(facilities, lat, lng, radius_m, category) == _scan_within(facilities, lat, lng, radius_m, category)


def test_the_index_follows_a_replaced_facility_list() -> None:
    first, second = _facilities(60, 7), _facilities(60, 8)
    assert _nearest(first, *TORONTO, "urgent") == _scan_nearest(first, *TORONTO, "urgent", 3)
    assert _nearest(second, *TORONTO, "urgent") == _scan_nearest(second, *TORONTO, "urgent", 3)


def test_a_short_list_is_left_to_the_scan(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cell_index, "MIN_INDEXED", 1000)
    facilities = _facilities(304, 9)
    assert cell_index.nearest(facilities, *TORONTO, lambda f: True, 3, lambda f: 0.0) is None
    assert cell_index.within_radius(facilities, *TORONTO, 5.0) is None
    assert _nearest(facilities, *TORONTO, "urgent") == _scan_nearest(facilities, *TORONTO, "urgent", 3)
    assert _within(facilities, *TORONTO, 5000, None) == _scan_within(facilities, *TORONTO, 5000, None)


def test_the_rings_needed_grow_with_the_distance() -> None:
    assert cell_index.rings_covering(0) >= 1
    assert cell_index.rings_covering(1) < cell_index.rings_covering(5) < cell_index.rings_covering(15)
    assert cell_index.rings_covering(19) <= cell_index.MAX_RINGS < cell_index.rings_covering(25)
