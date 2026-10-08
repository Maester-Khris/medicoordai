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

from models import AppConfig, FeedbackRequest, GuestEventRequest

_SID = "00000000-0000-0000-0000-0000000000a1"
_MID = "00000000-0000-0000-0000-0000000000a2"


def test_feedback_request_accepts_up_and_down_only() -> None:
    assert FeedbackRequest(session_id=_SID, message_id=_MID, thumb="up").comment is None
    with pytest.raises(ValidationError):
        FeedbackRequest(session_id=_SID, message_id=_MID, thumb="meh")


def test_feedback_comment_is_capped_at_2000_chars() -> None:
    with pytest.raises(ValidationError):
        FeedbackRequest(session_id=_SID, message_id=_MID, thumb="down", comment="x" * 2001)


def test_guest_event_only_accepts_route_drawn_from_clients() -> None:
    assert GuestEventRequest(type="route_drawn", session_id=_SID).type == "route_drawn"
    with pytest.raises(ValidationError):
        GuestEventRequest(type="session_started", session_id=_SID)


def test_app_config_shape() -> None:
    cfg = AppConfig(demo_mode=True, starter_prompts=["a"],
                    downtown_fallback={"lat": 43.6532, "lng": -79.3832}, modes_enabled=["car"])
    assert cfg.model_dump()["downtown_fallback"] == {"lat": 43.6532, "lng": -79.3832}


def test_facility_carries_wait_details() -> None:
    fields = Facility.model_fields
    assert "raw_wait" in fields and "predicted" in fields
