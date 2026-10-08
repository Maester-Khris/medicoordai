"""Travel routes from one origin to a few candidate facilities.

One Geoapify Routing call per candidate, all awaited together on one async client. Route Matrix
is not used: it rejects the transit mode, and one Routing call already returns time, distance and
the road shape. A candidate whose call fails comes back with nulls; it never fails the others.

The API key travels in the query string, so an httpx error message contains it. Nothing here logs
an exception's text, only its type.
"""
import asyncio
import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)

GEOAPIFY_MODES = {"car": "drive", "bike": "bicycle", "walk": "walk", "bus": "transit"}


class RoutingNotConfigured(Exception):
    pass


def parse_route(payload: dict[str, Any]) -> dict[str, Any] | None:
    features = payload.get("features", [])
    if not features:
        return None
    feature = features[0]
    props = feature.get("properties", {})
    time_s = props.get("time")
    distance_m = props.get("distance")
    if time_s is None or distance_m is None:
        return None

    geom = feature.get("geometry", {})
    geom_type = geom.get("type")
    if geom_type not in ("LineString", "MultiLineString"):
        return None

    coords: list[list[float]] = []
    raw_coords = geom.get("coordinates", [])
    if geom_type == "LineString":
        for lng, lat in raw_coords:
            coords.append([lat, lng])
    elif geom_type == "MultiLineString":
        for segment in raw_coords:
            for lng, lat in segment:
                coords.append([lat, lng])

    if not coords:
        return None

    return {
        "eta_minutes": round(time_s / 60),
        "distance_km": round(distance_m / 1000, 1),
        "geometry": coords,
    }


async def _fetch_one(
    client: httpx.AsyncClient, origin: dict[str, float], facility: dict[str, Any], api_mode: str, key: str
) -> dict[str, Any]:
    url = "https://api.geoapify.com/v1/routing"
    params = {
        "waypoints": f"{origin['lat']},{origin['lng']}|{facility['lat']},{facility['lng']}",
        "mode": api_mode,
        "apiKey": key,
    }
    empty_result = {
        "facility_id": facility["id"],
        "eta_minutes": None,
        "distance_km": None,
        "geometry": None,
    }
    try:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        parsed = parse_route(resp.json())
        if parsed:
            return {"facility_id": facility["id"], **parsed}
        return empty_result
    except Exception as e:
        logger.debug("routing_candidate_failed", extra={"mode": api_mode, "facility": facility["id"], "error": type(e).__name__})
        return empty_result


async def routes_for(
    origin: dict[str, float],
    facilities: list[dict[str, Any]],
    mode: str,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> list[dict[str, Any]]:
    key = os.environ.get("GEOAPIFY_API_KEY", "").strip()
    if not key:
        raise RoutingNotConfigured("GEOAPIFY_API_KEY is not set")

    api_mode = GEOAPIFY_MODES[mode]

    async with httpx.AsyncClient(transport=transport, timeout=httpx.Timeout(8.0, connect=3.0)) as client:
        tasks = [_fetch_one(client, origin, fac, api_mode, key) for fac in facilities]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    final_results = []
    for fac, res in zip(facilities, results):
        if isinstance(res, Exception):
            logger.debug("routing_candidate_failed", extra={"mode": api_mode, "facility": fac["id"], "error": type(res).__name__})
            final_results.append(
                {
                    "facility_id": fac["id"],
                    "eta_minutes": None,
                    "distance_km": None,
                    "geometry": None,
                }
            )
        else:
            final_results.append(res)

    return final_results


def fastest_facility_id(routes: list[dict[str, Any]]) -> str | None:
    valid = [r for r in routes if r.get("eta_minutes") is not None]
    if not valid:
        return None
    fastest = min(valid, key=lambda r: r["eta_minutes"])
    return fastest["facility_id"]
