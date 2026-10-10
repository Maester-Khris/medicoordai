import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from middleware.auth import get_actor
from routers import routes
from services import routing

GUEST = "3f2b1c9e-8a47-4d1e-9c55-0a1b2c3d4e5f"
FACILITIES = [
    {"id": "a", "lat": 43.6596, "lng": -79.3884},
    {"id": "b", "lat": 43.7224, "lng": -79.3763},
    {"id": "c", "lat": 43.7557, "lng": -79.2470},
]
BODY = {"origin": {"lat": 43.6532, "lng": -79.3832}, "facility_ids": ["a", "b"], "mode": "bike"}
LINE = [[43.65, -79.38], [43.66, -79.39]]


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
    app.include_router(routes.router)
    return TestClient(app)


def _found(fid: str, eta: int) -> dict:
    return {"facility_id": fid, "eta_minutes": eta, "distance_km": 4.2, "geometry": LINE}


def _missing(fid: str) -> dict:
    return {"facility_id": fid, "eta_minutes": None, "distance_km": None, "geometry": None}


@pytest.fixture(autouse=True)
def _defaults(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DEMO_MODE", "true")
    with patch.object(routes, "get_cached_facilities", return_value=(FACILITIES, '"etag"')), \
         patch.object(routes, "check_rate_limit", return_value=None) as limiter:
        yield limiter


def test_routes_are_returned_with_the_fastest_candidate() -> None:
    fake = AsyncMock(return_value=[_found("a", 20), _found("b", 9)])
    with patch.object(routes.routing, "routes_for", fake):
        resp = _client().post("/routes", json=BODY)

    assert resp.status_code == 200
    body = resp.json()
    assert body["mode"] == "bike" and body["fastest_facility_id"] == "b"
    assert [r["facility_id"] for r in body["routes"]] == ["a", "b"]
    assert body["routes"][0]["geometry"] == LINE
    origin, facilities, mode = fake.call_args.args
    assert origin == {"lat": 43.6532, "lng": -79.3832} and mode == "bike"
    assert [f["id"] for f in facilities] == ["a", "b"]  # coordinates come from the cache, not the request


def test_a_candidate_without_a_route_is_returned_with_nulls() -> None:
    with patch.object(routes.routing, "routes_for", AsyncMock(return_value=[_found("a", 20), _missing("b")])):
        body = _client().post("/routes", json=BODY).json()
    assert body["fastest_facility_id"] == "a" and body["routes"][1]["eta_minutes"] is None


def test_all_candidates_failing_is_502() -> None:
    with patch.object(routes.routing, "routes_for", AsyncMock(return_value=[_missing("a"), _missing("b")])):
        assert _client().post("/routes", json=BODY).status_code == 502


def test_unknown_facility_is_404_and_makes_no_routing_call() -> None:
    fake = AsyncMock()
    with patch.object(routes.routing, "routes_for", fake):
        resp = _client().post("/routes", json={**BODY, "facility_ids": ["a", "nope"]})
    assert resp.status_code == 404
    fake.assert_not_called()


def test_empty_cache_is_503() -> None:
    with patch.object(routes, "get_cached_facilities", return_value=(None, None)):
        assert _client().post("/routes", json=BODY).status_code == 503


def test_missing_api_key_is_503() -> None:
    with patch.object(routes.routing, "routes_for", AsyncMock(side_effect=routing.RoutingNotConfigured("x"))):
        assert _client().post("/routes", json=BODY).status_code == 503


@pytest.mark.parametrize("patch_body", [
    {"facility_ids": []},
    {"facility_ids": ["a", "b", "c", "d"]},
    {"facility_ids": ["a", "a"]},
    {"mode": "plane"},
    {"origin": {"lat": 120, "lng": 0}},
])
def test_invalid_bodies_are_422(patch_body: dict) -> None:
    assert _client().post("/routes", json={**BODY, **patch_body}).status_code == 422


def test_a_mode_that_is_not_enabled_is_422(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(routes.config, "DEMO_MODES", ["car"])
    assert _client().post("/routes", json=BODY).status_code == 422


def test_guest_over_the_limit_gets_the_busy_response(_defaults) -> None:
    _defaults.return_value = 240
    fake = AsyncMock()
    with patch.object(routes.routing, "routes_for", fake):
        resp = _client().post("/routes", json=BODY)
    assert resp.status_code == 429 and resp.json() == {"code": "busy", "retry_after": 240}
    assert resp.headers["retry-after"] == "240"
    fake.assert_not_called()


def test_guests_are_counted_in_the_routes_bucket(_defaults) -> None:
    with patch.object(routes.routing, "routes_for", AsyncMock(return_value=[_found("a", 5), _found("b", 6)])):
        _client().post("/routes", json=BODY)
    assert _defaults.call_args.args[0] == GUEST
    assert _defaults.call_args.kwargs == {"bucket": "routes"}


def test_signed_in_users_are_not_rate_limited(_defaults, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEMO_MODE")
    with patch.object(routes.routing, "routes_for", AsyncMock(return_value=[_found("a", 5), _found("b", 6)])):
        assert _client(_User).post("/routes", json=BODY).status_code == 200
    _defaults.assert_not_called()
