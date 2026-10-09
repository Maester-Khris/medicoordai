import logging
import os
import hashlib
import json
import demo_db
from config import demo_mode
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, JSONResponse
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from starlette.concurrency import run_in_threadpool
from services.facilities import get_all_facilities, apply_wait_filter, annotate_wait_details
from services.wait_times import get_wait_map, get_wait_minutes_map
from db import supabase_rpc
from models import NearbyFacilityResult
from middleware.auth import AuthMiddleware, get_current_user
from cache import get_cached_facilities, set_cached_facilities
from graph.factory import close_graph_provider, get_graph_provider
from observability import init_observability, verify_metrics_token, RequestIDMiddleware, _registry
from routers.chat import router as chat_router
from routers.notifications import router as notifications_router
from routers.demo import router as demo_router
from routers.routes import router as routes_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if demo_mode():
        try:
            demo_db.open_pool()
        except Exception as exc:
            logger.warning("demo_db_pool_open_failed", extra={"error_type": type(exc).__name__})
    try:
        data = get_all_facilities()
        set_cached_facilities(data)
        logger.info("cache_warm", extra={"facility_count": len(data)})
    except Exception as exc:
        logger.warning("cache_warm_failed", extra={"error_type": type(exc).__name__})
    yield
    close_graph_provider()
    demo_db.close_pool()


app = FastAPI(title="MediCoord AI API", version="0.1.0", lifespan=lifespan)

ALLOWED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get("ALLOWED_ORIGINS", "http://localhost:5173").split(",")
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Authorization", "X-Request-ID", "If-None-Match", "X-Guest-Id", "X-Internal"],
)
app.add_middleware(AuthMiddleware)
app.add_middleware(RequestIDMiddleware)

init_observability(app)
app.include_router(chat_router)
app.include_router(notifications_router)
app.include_router(demo_router)
app.include_router(routes_router)


@app.get("/metrics")
async def metrics(_: None = Depends(verify_metrics_token)) -> Response:
    return Response(
        content=generate_latest(_registry),
        media_type=CONTENT_TYPE_LATEST,
    )


@app.get("/")
def root() -> dict:
    return {
        "service": "MediCoord AI API",
        "version": "0.1.0",
        "status": "running",
    }


@app.get("/health")
def health() -> dict:
    result = {
        "status": "ok",
        "llmProvider": os.environ.get("LLM_PROVIDER", "groq"),
    }
    result["demoMode"] = demo_mode()
    if demo_mode():
        try:
            demo_db.fetch_one("select 1 as ok")
            result["demoDb"] = "ok"
        except Exception as exc:
            result["demoDb"] = "unreachable"
            logger.warning("demo_db_health_failed", extra={"error_type": type(exc).__name__})
    # Doubles as a keep-alive ping for AuraDB's free-tier 72h auto-pause
    # window (graph/snomed_neo4j/provider.py) — meant to be polled by an
    # external cronjob, not just a status check.
    if os.environ.get("GRAPH_RAG_PROVIDER", "off").lower() == "neo4j":
        try:
            get_graph_provider().ping()
            result["neo4j"] = "ok"
        except Exception as exc:
            result["neo4j"] = "unreachable"
            logger.warning("neo4j_health_ping_failed", extra={"error_type": type(exc).__name__})
    return result


@app.get("/me")
async def me(current_user: object = Depends(get_current_user)) -> dict:
    return {"user_id": current_user.id, "email": current_user.email}  # type: ignore[attr-defined]


@app.get("/facilities")
async def facilities(
    request: Request,
    category: str | None = None,
    severity: str | None = None,
    max_wait_minutes: int | None = None,
) -> Response:
    cached_data, _ = get_cached_facilities()

    # `cache.py` has no TTL/invalidation. `cached_data is None` alone isn't enough:
    # if the lifespan warm-up ran before Supabase had rows (or before they were
    # marked is_operational), it caches `[]` — not None — and every request since
    # would serve that empty snapshot forever. Treat an empty cache as not-yet-warm
    # too, so it self-heals on the next request once real data exists.
    if not cached_data:
        raw = get_all_facilities(category=None, severity=None)
        cached_etag = set_cached_facilities(raw)
        cached_data = raw

    data: list[dict] = cached_data
    if category:
        data = [r for r in data if r["category"] == category]
    if severity:
        data = [r for r in data if severity in r.get("accepted_severity", [])]

    wait_info = await run_in_threadpool(get_wait_map)
    wait_minutes = {fid: info["wait_minutes"] for fid, info in wait_info.items()}
    data = apply_wait_filter(data, "id", max_wait_minutes, wait_minutes)
    data = annotate_wait_details(data, "id", wait_info)

    filtered_etag = f'"{hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()[:32]}"'

    if request.headers.get("If-None-Match", "") == filtered_etag:
        return Response(status_code=304)

    return JSONResponse(
        content=data,
        headers={"ETag": filtered_etag, "Cache-Control": "no-cache"},
    )


@app.get("/facilities/nearby")
async def facilities_nearby(
    lat:      float,
    lng:      float,
    radius_m: int = 5000,
    category: str | None = None,
    max_wait_minutes: int | None = None,
) -> list[NearbyFacilityResult]:
    try:
        data = await run_in_threadpool(
            supabase_rpc,
            "nearby_facilities",
            {
                "user_lat":       lat,
                "user_lng":       lng,
                "radius_m":       min(radius_m, 50000),
                "facility_types": [category] if category else None,
                "result_limit":   50,
            },
        ) or []
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"proximity search failed: {exc}") from exc

    wait_map = await run_in_threadpool(get_wait_minutes_map)
    return apply_wait_filter(data, "facility_id", max_wait_minutes, wait_map)
