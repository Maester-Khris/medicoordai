import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx
import pytest

from services import routing

ORIGIN = {"lat": 43.6532, "lng": -79.3832}
A = {"id": "a", "lat": 43.6596, "lng": -79.3884}
PAYLOAD = {"features": [{
    "properties": {"time": 600, "distance": 4200},
    "geometry": {"type": "LineString", "coordinates": [[-79.38, 43.65], [-79.39, 43.66]]},
}]}


def _called_paths(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    monkeypatch.setenv("GEOAPIFY_API_KEY", "k")
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(f"{request.url.scheme}://{request.url.host}:{request.url.port}{request.url.path}")
        return httpx.Response(200, json=PAYLOAD)

    routes = asyncio.run(routing.routes_for(ORIGIN, [A], "car", transport=httpx.MockTransport(handler)))
    assert routes[0]["eta_minutes"] == 10
    return seen


def test_the_base_url_setting_moves_the_routing_call(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEOAPIFY_BASE_URL", "http://mock:9000/")
    assert _called_paths(monkeypatch) == ["http://mock:9000/v1/routing"]


def test_without_the_setting_the_call_goes_to_geoapify(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEOAPIFY_BASE_URL", raising=False)
    assert _called_paths(monkeypatch) == ["https://api.geoapify.com:None/v1/routing"]


def test_an_estimated_route_has_a_time_and_a_distance_and_no_road_shape() -> None:
    route = routing.estimated_route(ORIGIN, A, "walk")
    assert route["facility_id"] == "a" and route["estimated"] is True and route["geometry"] is None
    assert route["distance_km"] == 0.8
    assert route["eta_minutes"] == 10  # 0.82 km at walking speed


def test_an_estimate_is_never_zero_minutes() -> None:
    next_door = {"id": "n", "lat": ORIGIN["lat"], "lng": ORIGIN["lng"]}
    assert routing.estimated_route(ORIGIN, next_door, "car")["eta_minutes"] == 1
