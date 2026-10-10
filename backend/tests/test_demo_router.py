import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from middleware.auth import get_actor
from routers import demo

GUEST = "3f2b1c9e-8a47-4d1e-9c55-0a1b2c3d4e5f"
SID = "00000000-0000-0000-0000-0000000000a1"
MID = "00000000-0000-0000-0000-0000000000a2"


class _Guest:
    id = GUEST
    email = None
    is_guest = True


class _User:
    id = "u-1"
    email = "a@b.c"
    is_guest = False


def _client(actor: object = _Guest) -> TestClient:
    app = FastAPI()
    app.dependency_overrides[get_actor] = lambda: actor()
    app.include_router(demo.router)
    return TestClient(app)


def test_config_in_demo_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.delenv("DEMO_STARTER_PROMPTS", raising=False)
    body = _client().get("/config").json()
    assert body["demo_mode"] is True and body["modes_enabled"] == ["car", "bike", "bus", "walk"]
    assert body["downtown_fallback"] == {"lat": 43.6532, "lng": -79.3832}
    assert len(body["starter_prompts"]) == 3


def test_config_with_flag_off_enables_every_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEMO_MODE", raising=False)
    body = _client().get("/config").json()
    assert body["demo_mode"] is False and body["modes_enabled"] == ["car", "bike", "bus", "walk"]


def test_config_needs_no_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEMO_MODE", "true")
    app = FastAPI()
    app.include_router(demo.router)  # no get_actor override: the route must not depend on it
    assert TestClient(app).get("/config").status_code == 200


def test_feedback_is_stored() -> None:
    with patch.object(demo.guest_store, "upsert_feedback", return_value=True) as upsert:
        resp = _client().post("/feedback", json={"session_id": SID, "message_id": MID,
                                                 "thumb": "down", "comment": "  wrong place  "})
    assert resp.status_code == 204 and resp.content == b""
    upsert.assert_called_once_with(GUEST, SID, MID, "down", "wrong place")


def test_blank_comment_is_stored_as_null() -> None:
    with patch.object(demo.guest_store, "upsert_feedback", return_value=True) as upsert:
        _client().post("/feedback", json={"session_id": SID, "message_id": MID, "thumb": "up", "comment": "   "})
    assert upsert.call_args.args[4] is None


def test_feedback_for_unknown_message_is_404() -> None:
    with patch.object(demo.guest_store, "upsert_feedback", return_value=False):
        resp = _client().post("/feedback", json={"session_id": SID, "message_id": MID, "thumb": "up"})
    assert resp.status_code == 404


def test_feedback_validates_the_body() -> None:
    assert _client().post("/feedback", json={"session_id": SID, "message_id": MID, "thumb": "meh"}).status_code == 422
    assert _client().post("/feedback", json={"session_id": "x", "message_id": MID, "thumb": "up"}).status_code == 422


def test_signed_in_users_cannot_post_guest_feedback_or_events() -> None:
    client = _client(_User)
    assert client.post("/feedback", json={"session_id": SID, "message_id": MID, "thumb": "up"}).status_code == 404
    assert client.post("/events", json={"type": "route_drawn", "session_id": SID}).status_code == 404


def test_route_drawn_event_is_recorded() -> None:
    with patch.object(demo.guest_store, "record_event", return_value=True) as record:
        resp = _client().post("/events", json={"type": "route_drawn", "session_id": SID, "mode": "bus"})
    assert resp.status_code == 204
    record.assert_called_once_with(GUEST, "route_drawn", SID, "bus", None)


def test_route_drawn_without_a_mode_is_still_accepted() -> None:
    with patch.object(demo.guest_store, "record_event", return_value=True) as record:
        resp = _client().post("/events", json={"type": "route_drawn", "session_id": SID})
    assert resp.status_code == 204
    record.assert_called_once_with(GUEST, "route_drawn", SID, None, None)


def test_mode_changed_event_is_recorded_with_its_duration() -> None:
    with patch.object(demo.guest_store, "record_event", return_value=True) as record:
        resp = _client().post(
            "/events", json={"type": "mode_changed", "session_id": SID, "mode": "walk", "duration_ms": 1234}
        )
    assert resp.status_code == 204
    record.assert_called_once_with(GUEST, "mode_changed", SID, "walk", 1234)


def test_mode_changed_without_a_mode_is_422() -> None:
    assert _client().post("/events", json={"type": "mode_changed", "session_id": SID}).status_code == 422


def test_event_for_foreign_session_is_404() -> None:
    with patch.object(demo.guest_store, "record_event", return_value=False):
        assert _client().post("/events", json={"type": "route_drawn", "session_id": SID}).status_code == 404


def test_clients_cannot_post_server_side_events() -> None:
    resp = _client().post("/events", json={"type": "recommendation_shown", "session_id": SID})
    assert resp.status_code == 422
