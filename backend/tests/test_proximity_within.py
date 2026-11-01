import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import patch

from services import proximity

ORIGIN = (43.6532, -79.3832)


def _facility(fid: str, lat: float, lng: float, category: str = "hospital", **extra: object) -> dict:
    return {"id": fid, "name": f"Facility {fid}", "category": category, "address": "1 Main St",
            "lat": lat, "lng": lng, "phone": None, **extra}


NEAR = _facility("near", 43.6596, -79.3884)                       # about 0.8 km
MID = _facility("mid", 43.7224, -79.3763, category="ambulatory")  # about 7.7 km
FAR = _facility("far", 43.7557, -79.2470)                         # about 15.8 km


def _within(radius_m: int, category: str | None = None, cache: list[dict] | None = None):
    data = [FAR, NEAR, MID] if cache is None else cache
    with patch.object(proximity, "get_cached_facilities", return_value=(data, '"etag"')):
        return proximity.find_facilities_within(*ORIGIN, radius_m, category)


def test_results_are_sorted_by_distance_and_cut_at_the_radius() -> None:
    rows = _within(10000)
    assert [r["facility_id"] for r in rows] == ["near", "mid"]
    assert rows[0]["distance_m"] < rows[1]["distance_m"] <= 10000


def test_category_filter() -> None:
    assert [r["facility_id"] for r in _within(50000, "ambulatory")] == ["mid"]


def test_radius_boundary_is_inclusive() -> None:
    exact = _within(50000, cache=[NEAR])[0]["distance_m"]
    assert [r["facility_id"] for r in _within(exact, cache=[NEAR])] == ["near"]
    assert _within(exact - 1, cache=[NEAR]) == []


def test_radius_is_capped_at_fifty_kilometres() -> None:
    very_far = _facility("ottawa", 45.4215, -75.6972)  # about 350 km
    assert _within(1_000_000, cache=[very_far]) == []


def test_row_has_the_contract_shape() -> None:
    row = _within(10000, cache=[_facility("near", 43.6596, -79.3884, phone="416-555-0100")])[0]
    assert row == {
        "facility_id": "near",
        "facility_name": "Facility near",
        "category": "hospital",
        "address": "1 Main St",
        "phone": "416-555-0100",
        "is_operational": True,
        "distance_m": row["distance_m"],
        "eta_walk_min": round(row["distance_m"] / 1.4 / 60),
        "eta_transit_min": round(row["distance_m"] / 6.0 / 60),
        "eta_drive_min": round(row["distance_m"] / 11.0 / 60),
    }
    assert 700 < row["distance_m"] < 900


def test_at_most_fifty_rows() -> None:
    many = [_facility(f"f{i}", 43.6532 + i * 0.0001, -79.3832) for i in range(80)]
    assert len(_within(50000, cache=many)) == 50


def test_facilities_without_coordinates_or_address_do_not_break_the_search() -> None:
    rows = _within(50000, cache=[_facility("nocoords", None, None), _facility("noaddr", 43.6596, -79.3884, address=None)])
    assert [r["facility_id"] for r in rows] == ["noaddr"] and rows[0]["address"] == ""


def test_empty_cache_returns_none() -> None:
    with patch.object(proximity, "get_cached_facilities", return_value=(None, None)):
        assert proximity.find_facilities_within(*ORIGIN, 5000) is None
    assert _within(5000, cache=[]) is None
