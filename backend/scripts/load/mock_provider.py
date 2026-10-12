"""Stand-in for the two metered providers (Groq chat completions, Geoapify routing), for load tests.

Point the API at it with GROQ_BASE_URL and GEOAPIFY_BASE_URL on the staging service only. It
answers with the shape of the real replies after a delay drawn from a distribution, so the test
measures this API and not the providers' quotas.

    uvicorn scripts.load.mock_provider:app --host 0.0.0.0 --port 8080

Settings (all optional; defaults reproduce Sprint 21):
    MOCK_LLM_MEAN_S       mean LLM call time, seconds (2.2)
    MOCK_LLM_SIGMA        spread of the LLM call time, log-normal (0.4)
    MOCK_ROUTE_P50_S      median routing call time (1.0)
    MOCK_ROUTE_P95_S      95th percentile routing call time (1.9)
    MOCK_ROUTE_POINTS     points in a route's geometry (200)
    MOCK_DELAY_SCALE      multiplies every delay; 0 answers at once (1)

GET /stats counts what the API sent, POST /stats/reset zeroes it.
"""
import asyncio
import json
import math
import os
import random
import re
import time
import uuid

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

app = FastAPI(title="MediCoord provider mock")

# ponytail: fixed mix and token counts. Sprint 21 measured about 1,820 prompt and 690 completion
# tokens over two calls per turn; make these settings if a run needs another shape.
SEVERITY_WEIGHTS = {"routine": 25, "moderate": 40, "urgent": 25, "emergent": 10}
PROMPT_TOKENS = 910
COMPLETION_TOKENS = 345
SPEED_KMH = {"drive": 40.0, "bicycle": 15.0, "walk": 5.0, "transit": 25.0}

_FACILITY_IN_GROUNDING = re.compile(r"nearest appropriate facility is: (.+?) at ")
_SEVERITY_IN_GROUNDING = re.compile(r"classified as: (\w+)")

_stats: dict[str, int] = {}
_in_flight = 0


def reset_stats() -> None:
    global _in_flight
    _stats.clear()
    _stats.update(llm_calls=0, llm_tool_calls=0, routing_calls=0, max_user_turns_seen=0, peak_in_flight=0)
    _in_flight = 0


reset_stats()


def _float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, "").strip() or default)
    except ValueError:
        return default


def _scale() -> float:
    return _float("MOCK_DELAY_SCALE", 1.0)


def llm_delay_seconds() -> float:
    """Log-normal with the configured mean."""
    sigma = _float("MOCK_LLM_SIGMA", 0.4)
    median = _float("MOCK_LLM_MEAN_S", 2.2) / math.exp(sigma * sigma / 2)
    return random.lognormvariate(math.log(median), sigma) * _scale()


def route_delay_seconds() -> float:
    """Log-normal through the configured median and 95th percentile."""
    p50 = _float("MOCK_ROUTE_P50_S", 1.0)
    p95 = _float("MOCK_ROUTE_P95_S", 1.9)
    sigma = math.log(p95 / p50) / 1.645
    return random.lognormvariate(math.log(p50), sigma) * _scale()


async def _hold(seconds: float) -> None:
    """Counts the call as in flight while it waits, so /stats shows the concurrency reached."""
    global _in_flight
    _in_flight += 1
    _stats["peak_in_flight"] = max(_stats["peak_in_flight"], _in_flight)
    try:
        await asyncio.sleep(seconds)
    finally:
        _in_flight -= 1


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "mock": True}


@app.get("/stats")
def stats() -> dict:
    return dict(_stats)


@app.post("/stats/reset")
def stats_reset() -> dict:
    reset_stats()
    return dict(_stats)


@app.post("/openai/v1/chat/completions")
async def chat_completions(request: Request) -> JSONResponse:
    body = await request.json()
    messages = body.get("messages") or []
    tools = body.get("tools") or []
    _stats["llm_calls"] += 1
    user_turns = sum(1 for m in messages if m.get("role") == "user")
    _stats["max_user_turns_seen"] = max(_stats["max_user_turns_seen"], user_turns)
    await _hold(llm_delay_seconds())

    message: dict
    if tools:
        # The agent suppresses a triage that comes too early, so always offering one keeps the
        # real turn-count rules in play.
        _stats["llm_tool_calls"] += 1
        severity = random.choices(list(SEVERITY_WEIGHTS), weights=list(SEVERITY_WEIGHTS.values()))[0]
        arguments = {"severity": severity, "reasoning": "Mock classification.", "information_sufficient": True}
        message = {
            "role": "assistant",
            "content": None,
            "tool_calls": [{
                "id": f"call_{uuid.uuid4().hex[:24]}",
                "type": "function",
                "function": {"name": tools[0]["function"]["name"], "arguments": json.dumps(arguments)},
            }],
        }
        finish = "tool_calls"
    else:
        grounding = next((m.get("content") or "" for m in reversed(messages) if m.get("role") == "system"), "")
        facility = _FACILITY_IN_GROUNDING.search(grounding)
        severity_found = _SEVERITY_IN_GROUNDING.search(grounding)
        text = "Based on what you described, this looks " + (severity_found.group(1) if severity_found else "routine")
        text += (
            f". The nearest appropriate facility is {facility.group(1)}. Please go there for assessment."
            if facility else
            ". Please call 211 or search online for nearby care."
        )
        message = {"role": "assistant", "content": text}
        finish = "stop"

    return JSONResponse({
        "id": f"chatcmpl-{uuid.uuid4().hex[:24]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": body.get("model", "mock"),
        "choices": [{"index": 0, "message": message, "finish_reason": finish}],
        "usage": {
            "prompt_tokens": PROMPT_TOKENS,
            "completion_tokens": COMPLETION_TOKENS,
            "total_tokens": PROMPT_TOKENS + COMPLETION_TOKENS,
        },
    })


def _haversine_km(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lng1, lat2, lng2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(h))


@app.get("/v1/routing")
async def routing(waypoints: str = "", mode: str = "drive") -> JSONResponse:
    try:
        (lat1, lng1), (lat2, lng2) = (tuple(float(v) for v in p.split(",")) for p in waypoints.split("|"))
    except ValueError:
        raise HTTPException(400, "waypoints must be 'lat,lng|lat,lng'") from None
    _stats["routing_calls"] += 1
    await _hold(route_delay_seconds())

    points = max(2, int(_float("MOCK_ROUTE_POINTS", 200)))
    # [lng, lat] like Geoapify, as one MultiLineString line.
    line = [
        [lng1 + (lng2 - lng1) * i / (points - 1), lat1 + (lat2 - lat1) * i / (points - 1)]
        for i in range(points)
    ]
    distance_km = _haversine_km((lat1, lng1), (lat2, lng2))
    seconds = distance_km / SPEED_KMH.get(mode, SPEED_KMH["drive"]) * 3600
    return JSONResponse({
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "properties": {"mode": mode, "distance": round(distance_km * 1000), "time": round(seconds)},
            "geometry": {"type": "MultiLineString", "coordinates": [line]},
        }],
    })
