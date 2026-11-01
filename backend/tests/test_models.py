import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from models import Facility, NearbyFacilityResult


class TestFacilityWaitMinutes:
    def test_defaults_to_none(self):
        f = Facility(
            name="X", category="hospital", source_facility_type="general",
            accepted_severity=["routine"], address="123 St", lat=0.0, lng=0.0,
        )
        assert f.wait_minutes is None

    def test_accepts_explicit_value(self):
        f = Facility(
            name="X", category="hospital", source_facility_type="general",
            accepted_severity=["routine"], address="123 St", lat=0.0, lng=0.0,
            wait_minutes=15,
        )
        assert f.wait_minutes == 15


class TestNearbyFacilityResultWaitMinutes:
    def test_accepts_explicit_value(self):
        r = NearbyFacilityResult(
            facility_id="a", facility_name="X", category="hospital", address="123",
            phone=None, is_operational=True, distance_m=1, eta_walk_min=1,
            eta_transit_min=1, eta_drive_min=1, wait_minutes=15,
        )
        assert r.wait_minutes == 15

    def test_defaults_to_none(self):
        r = NearbyFacilityResult(
            facility_id="a", facility_name="X", category="hospital", address="123",
            phone=None, is_operational=True, distance_m=1, eta_walk_min=1,
            eta_transit_min=1, eta_drive_min=1,
        )
        assert r.wait_minutes is None

import pytest
from pydantic import ValidationError

from models import AppConfig, FeedbackRequest, GuestEventRequest, RoutesRequest, RoutesResponse

_SID = "00000000-0000-0000-0000-0000000000a1"
_MID = "00000000-0000-0000-0000-0000000000a2"


def test_feedback_request_accepts_up_and_down_only() -> None:
    assert FeedbackRequest(session_id=_SID, message_id=_MID, thumb="up").comment is None
    with pytest.raises(ValidationError):
        FeedbackRequest(session_id=_SID, message_id=_MID, thumb="meh")


def test_feedback_comment_is_capped_at_2000_chars() -> None:
    with pytest.raises(ValidationError):
        FeedbackRequest(session_id=_SID, message_id=_MID, thumb="down", comment="x" * 2001)





def test_app_config_shape() -> None:
    cfg = AppConfig(demo_mode=True, starter_prompts=["a"],
                    downtown_fallback={"lat": 43.6532, "lng": -79.3832}, modes_enabled=["car"])
    assert cfg.model_dump()["downtown_fallback"] == {"lat": 43.6532, "lng": -79.3832}


def test_facility_carries_wait_details() -> None:
    fields = Facility.model_fields
    assert "raw_wait" in fields and "predicted" in fields

_ORIGIN = {"lat": 43.6532, "lng": -79.3832}


def test_routes_request_accepts_one_to_three_unique_ids() -> None:
    body = RoutesRequest(origin=_ORIGIN, facility_ids=["a", "b", "c"], mode="bus")
    assert body.facility_ids == ["a", "b", "c"] and body.mode == "bus"


@pytest.mark.parametrize("ids", [[], ["a", "b", "c", "d"], ["a", "a"]])
def test_routes_request_rejects_bad_id_lists(ids: list[str]) -> None:
    with pytest.raises(ValidationError):
        RoutesRequest(origin=_ORIGIN, facility_ids=ids, mode="car")


@pytest.mark.parametrize("origin", [{"lat": 91, "lng": 0}, {"lat": 0, "lng": -181}])
def test_routes_request_rejects_out_of_range_origin(origin: dict) -> None:
    with pytest.raises(ValidationError):
        RoutesRequest(origin=origin, facility_ids=["a"], mode="car")


def test_routes_request_rejects_unknown_mode() -> None:
    with pytest.raises(ValidationError):
        RoutesRequest(origin=_ORIGIN, facility_ids=["a"], mode="plane")


def test_routes_response_allows_a_candidate_without_a_route() -> None:
    body = RoutesResponse(
        mode="car",
        routes=[
            {"facility_id": "a", "eta_minutes": 12, "distance_km": 4.2, "geometry": [[43.6, -79.3], [43.7, -79.4]]},
            {"facility_id": "b", "eta_minutes": None, "distance_km": None, "geometry": None},
        ],
        fastest_facility_id="a",
    )
    assert body.routes[1].geometry is None


def test_route_drawn_event_takes_an_optional_mode() -> None:
    assert GuestEventRequest(type="route_drawn", session_id=_SID).mode is None
    assert GuestEventRequest(type="route_drawn", session_id=_SID, mode="bike").mode == "bike"


def test_mode_changed_event_needs_a_mode() -> None:
    with pytest.raises(ValidationError):
        GuestEventRequest(type="mode_changed", session_id=_SID)
    event = GuestEventRequest(type="mode_changed", session_id=_SID, mode="walk", duration_ms=840)
    assert event.duration_ms == 840


@pytest.mark.parametrize("duration", [-1, 120001])
def test_mode_changed_duration_is_bounded(duration: int) -> None:
    with pytest.raises(ValidationError):
        GuestEventRequest(type="mode_changed", session_id=_SID, mode="car", duration_ms=duration)


def test_duration_is_rejected_on_route_drawn() -> None:
    with pytest.raises(ValidationError):
        GuestEventRequest(type="route_drawn", session_id=_SID, mode="car", duration_ms=5)
