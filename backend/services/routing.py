"""Travel routes from one origin to a few candidate facilities.

One Geoapify Routing call per candidate, all awaited together on one async client. Route Matrix
is not used: it rejects the transit mode, and one Routing call already returns time, distance and
the road shape. A candidate whose call fails comes back with nulls; it never fails the others.

The API key travels in the query string, so an httpx error message contains it. Nothing here logs
an exception's text, only its type, and httpx's own request log is raised to WARNING.
"""
import asyncio
import logging
import os

import httpx

logger = logging.getLogger(__name__)
# httpx logs every request URL at INFO, and the Geoapify key is in the query string.
logging.getLogger("httpx").setLevel(logging.WARNING)

GEOAPIFY_ROUTING_URL = "https://api.geoapify.com/v1/routing"
GEOAPIFY_MODES: dict[str, str] = {"car": "drive", "bike": "bicycle", "walk": "walk", "bus": "transit"}
ROUTE_TIMEOUT = httpx.Timeout(8.0, connect=3.0)  # slowest observed call (transit) was 2.9 s

NO_ROUTE: dict[str, None] = {"eta_minutes": None, "distance_km": None, "geometry": None}


class RoutingNotConfigured(RuntimeError):
    """GEOAPIFY_API_KEY is not set."""


def parse_route(payload: dict) -> dict | None:
    """Geoapify Routing response -> eta, distance and [lat, lng] points, or None if unusable."""
    features = payload.get("features") or []
    if not features:
        return None
    properties = features[0].get("properties") or {}
    geometry = features[0].get("geometry") or {}

    if geometry.get("type") == "MultiLineString":
        lines = geometry.get("coordinates") or []
    elif geometry.get("type") == "LineString":
        lines = [geometry.get("coordinates") or []]
    else:
        lines = []
    points = [[point[1], point[0]] for line in lines for point in line]  # Geoapify sends [lng, lat]

    time_s = properties.get("time")
    distance_m = properties.get("distance")
    if len(points) < 2 or time_s is None or distance_m is None:
        return None
    return {
        "eta_minutes": round(time_s / 60),
        "distance_km": round(distance_m / 1000, 1),
        "geometry": points,
    }


async def _fetch_route(
    client: httpx.AsyncClient, key: str, origin: dict[str, float], facility: dict, mode: str
) -> dict | None:
    params = {
        "waypoints": f"{origin['lat']},{origin['lng']}|{facility['lat']},{facility['lng']}",
        "mode": GEOAPIFY_MODES[mode],
        "apiKey": key,
    }
    try:
        response = await client.get(GEOAPIFY_ROUTING_URL, params=params)
        response.raise_for_status()
        parsed = parse_route(response.json())
    except (httpx.HTTPError, ValueError, TypeError, KeyError, IndexError) as exc:
        _log_failure(mode, facility, type(exc).__name__)
        return None
    if parsed is None:
        _log_failure(mode, facility, "NoRoute")
    return parsed


def _log_failure(mode: str, facility: dict, error_type: str) -> None:
    logger.warning(
        "routing_candidate_failed",
        extra={"mode": mode, "facility_id": str(facility["id"]), "error_type": error_type},
    )


async def routes_for(
    origin: dict[str, float],
    facilities: list[dict],
    mode: str,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> list[dict]:
    """One entry per facility, in the same order. `transport` exists for tests."""
    key = os.environ.get("GEOAPIFY_API_KEY", "").strip()
    if not key:
        raise RoutingNotConfigured("GEOAPIFY_API_KEY is not set")

    async with httpx.AsyncClient(timeout=ROUTE_TIMEOUT, transport=transport) as client:
        results = await asyncio.gather(
            *(_fetch_route(client, key, origin, facility, mode) for facility in facilities),
            return_exceptions=True,
        )

    routes: list[dict] = []
    for facility, result in zip(facilities, results):
        if isinstance(result, BaseException):  # anything _fetch_route did not expect
            _log_failure(mode, facility, type(result).__name__)
        found = result if isinstance(result, dict) else NO_ROUTE
        routes.append({"facility_id": str(facility["id"]), **found})
    return routes


def fastest_facility_id(routes: list[dict]) -> str | None:
    routed = [route for route in routes if route["eta_minutes"] is not None]
    if not routed:
        return None
    return min(routed, key=lambda route: route["eta_minutes"])["facility_id"]  # min keeps the first on a tie
