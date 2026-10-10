import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx
import pytest

from services import routing

ORIGIN = {"lat": 43.6532, "lng": -79.3832}
A = {"id": "a", "lat": 43.6596, "lng": -79.3884}
B = {"id": "b", "lat": 43.7224, "lng": -79.3763}
C = {"id": "c", "lat": 43.7557, "lng": -79.2470}
KEY = "test-key-do-not-log"


def _feature(time_s: float, distance_m: float, geometry: dict) -> dict:
    return {"features": [{"properties": {"time": time_s, "distance": distance_m}, "geometry": geometry}]}


MULTI = {"type": "MultiLineString", "coordinates": [[[-79.38, 43.65], [-79.39, 43.66]], [[-79.39, 43.66], [-79.40, 43.67]]]}
LINE = {"type": "LineString", "coordinates": [[-79.38, 43.65], [-79.37, 43.70]]}


@pytest.fixture(autouse=True)
def _key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEOAPIFY_API_KEY", KEY)


def _transport(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


def test_every_mode_key_maps_to_a_geoapify_mode() -> None:
    assert routing.GEOAPIFY_MODES == {"car": "drive", "bike": "bicycle", "walk": "walk", "bus": "transit"}


def test_parse_flattens_multilinestring_into_lat_lng_pairs() -> None:
    parsed = routing.parse_route(_feature(1080, 10040, MULTI))
    assert parsed == {
        "eta_minutes": 18,
        "distance_km": 10.0,
        "geometry": [[43.65, -79.38], [43.66, -79.39], [43.66, -79.39], [43.67, -79.40]],
    }


def test_parse_accepts_a_linestring() -> None:
    parsed = routing.parse_route(_feature(600, 5540, LINE))
    assert parsed is not None and parsed["geometry"] == [[43.65, -79.38], [43.70, -79.37]]
    assert parsed["eta_minutes"] == 10 and parsed["distance_km"] == 5.5


@pytest.mark.parametrize("payload", [
    {},
    {"features": []},
    {"features": [{"properties": {"time": 60}, "geometry": LINE}]},
    {"features": [{"properties": {"time": 60, "distance": 10}, "geometry": {"type": "Point", "coordinates": [0, 0]}}]},
])
def test_parse_returns_none_when_there_is_no_usable_route(payload: dict) -> None:
    assert routing.parse_route(payload) is None


@pytest.mark.asyncio
async def test_one_call_per_candidate_with_the_mapped_mode() -> None:
    seen: list[httpx.URL] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url)
        return httpx.Response(200, json=_feature(600, 5000, LINE))

    routes = await routing.routes_for(ORIGIN, [A, B, C], "bus", transport=_transport(handler))

    assert [r["facility_id"] for r in routes] == ["a", "b", "c"]
    assert len(seen) == 3
    assert {url.params["mode"] for url in seen} == {"transit"}
    assert "43.6532,-79.3832|43.6596,-79.3884" in {url.params["waypoints"] for url in seen}
    assert all(url.path == "/v1/routing" for url in seen)


@pytest.mark.asyncio
async def test_one_failing_candidate_keeps_the_others() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "43.7224" in request.url.params["waypoints"]:
            return httpx.Response(500, json={"error": "boom"})
        return httpx.Response(200, json=_feature(600, 5000, LINE))

    routes = await routing.routes_for(ORIGIN, [A, B, C], "car", transport=_transport(handler))

    assert routes[0]["eta_minutes"] == 10 and routes[2]["eta_minutes"] == 10
    assert routes[1] == {"facility_id": "b", "eta_minutes": None, "distance_km": None, "geometry": None}


@pytest.mark.asyncio
async def test_a_timeout_is_a_candidate_without_a_route() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    routes = await routing.routes_for(ORIGIN, [A], "walk", transport=_transport(handler))

    assert routes == [{"facility_id": "a", "eta_minutes": None, "distance_km": None, "geometry": None}]


@pytest.mark.asyncio
async def test_api_key_never_reaches_the_log(caplog: pytest.LogCaptureFixture) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"message": f"bad key {KEY}"})

    with caplog.at_level(logging.DEBUG):
        await routing.routes_for(ORIGIN, [A, B], "car", transport=_transport(handler))

    assert any(rec.getMessage() == "routing_candidate_failed" for rec in caplog.records)
    for rec in caplog.records:
        assert KEY not in rec.getMessage()
        assert KEY not in str(rec.__dict__)


@pytest.mark.asyncio
async def test_missing_key_raises_before_any_request(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEOAPIFY_API_KEY")
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={})

    with pytest.raises(routing.RoutingNotConfigured):
        await routing.routes_for(ORIGIN, [A], "car", transport=_transport(handler))
    assert calls == []


def _route(fid: str, eta: int | None) -> dict:
    return {"facility_id": fid, "eta_minutes": eta, "distance_km": None, "geometry": None}


def test_fastest_is_the_lowest_eta() -> None:
    assert routing.fastest_facility_id([_route("a", 20), _route("b", 7), _route("c", 9)]) == "b"


def test_fastest_tie_goes_to_the_earlier_candidate() -> None:
    assert routing.fastest_facility_id([_route("a", 9), _route("b", 9)]) == "a"


def test_fastest_ignores_candidates_without_a_route_and_can_be_none() -> None:
    assert routing.fastest_facility_id([_route("a", None), _route("b", 30)]) == "b"
    assert routing.fastest_facility_id([_route("a", None)]) is None
    assert routing.fastest_facility_id([]) is None


from observability import _registry


def _routing_count(mode: str, outcome: str) -> float:
    return _registry.get_sample_value("routing_call_duration_seconds_count", {"mode": mode, "outcome": outcome}) or 0.0


@pytest.mark.asyncio
async def test_each_candidate_call_is_timed_with_its_outcome() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        waypoints = request.url.params["waypoints"]
        if "43.7224" in waypoints:
            return httpx.Response(500, json={"error": "boom"})
        if "43.7557" in waypoints:
            return httpx.Response(200, json={"features": []})
        return httpx.Response(200, json=_feature(600, 5000, LINE))

    before = {o: _routing_count("bike", o) for o in ("ok", "error", "no_route", "timeout")}
    await routing.routes_for(ORIGIN, [A, B, C], "bike", transport=_transport(handler))

    assert _routing_count("bike", "ok") == before["ok"] + 1
    assert _routing_count("bike", "error") == before["error"] + 1
    assert _routing_count("bike", "no_route") == before["no_route"] + 1
    assert _routing_count("bike", "timeout") == before["timeout"]


@pytest.mark.asyncio
async def test_a_timeout_is_recorded_as_a_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    before = _routing_count("walk", "timeout")
    await routing.routes_for(ORIGIN, [A], "walk", transport=_transport(handler))
    assert _routing_count("walk", "timeout") == before + 1


@pytest.mark.asyncio
async def test_a_provider_status_code_is_logged_without_the_key(caplog: pytest.LogCaptureFixture) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"message": f"no route, key {KEY}"})

    with caplog.at_level(logging.WARNING):
        await routing.routes_for(ORIGIN, [A], "car", transport=_transport(handler))

    failed = [rec for rec in caplog.records if rec.getMessage() == "routing_candidate_failed"]
    assert [(rec.error_type, rec.status) for rec in failed] == [("HTTPStatusError", 400)]
    assert KEY not in str(failed[0].__dict__)
