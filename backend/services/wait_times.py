import json
import logging
import os

import redis
from prometheus_client import Counter

import demo_db
from config import demo_mode

from db import supabase_rpc
from observability import _registry

logger = logging.getLogger(__name__)

REDIS_HASH_KEY = "wait_times:current"

redis_client = redis.from_url(os.environ["UPSTASH_REDIS_URL"].strip(), decode_responses=True)

WAIT_TIMES_CACHE_OUTCOME = Counter(
    "wait_times_cache_outcome_total",
    "Outcome of each wait-time cache read, by branch",
    ["outcome"],
    registry=_registry,
)


def _wait_info(entry: dict) -> dict:
    return {
        "wait_minutes": entry.get("wait_minutes"),
        "raw_wait": entry.get("raw_wait"),
        "predicted": bool(entry.get("predicted", False)),
    }


def _fallback_rows() -> list[dict]:
    """Current wait rows from the database of record: demo Postgres, or the Supabase RPC."""
    if demo_mode():
        return demo_db.fetch_all(
            "select facility_id::text as facility_id, wait_minutes, raw_wait, predicted, "
            "source, recorded_at from wait_times"
        )
    return supabase_rpc("latest_wait_times", {})


def get_wait_map() -> dict[str, dict]:
    """
    Cache-aside read of current ER waits, keyed by facility_id. Each value is
    {"wait_minutes": int | None, "raw_wait": str | None, "predicted": bool}; a predicted
    range has wait_minutes None and its display text in raw_wait.

    1. Try the Redis hash workers/scraper.py writes every ~15 min. Each entry is parsed
       independently so one malformed value doesn't discard the others.
    2. On Redis error or an empty hash, fall back to the database (see _fallback_rows) and
       best-effort populate Redis for the next read.
    3. If both fail, degrade to an empty map rather than raising — missing wait data always
       passes filters.

    Each outcome increments WAIT_TIMES_CACHE_OUTCOME (redis_hit / supabase_fallback /
    total_failure); the label keeps its Sprint 17 name for dashboard continuity.
    """
    try:
        raw = redis_client.hgetall(REDIS_HASH_KEY)
    except Exception:
        logger.warning("redis_unavailable_falling_back_to_database")
        raw = None

    if raw:
        wait_map: dict[str, dict] = {}
        for fid, v in raw.items():
            try:
                wait_map[fid] = _wait_info(json.loads(v))
            except (ValueError, AttributeError, TypeError):
                logger.warning("wait_times_entry_malformed", extra={"facility_id": fid})
        if wait_map:
            WAIT_TIMES_CACHE_OUTCOME.labels(outcome="redis_hit").inc()
        return wait_map

    try:
        rows = _fallback_rows()
    except Exception:
        logger.warning("wait_times_fallback_failed_returning_empty")
        WAIT_TIMES_CACHE_OUTCOME.labels(outcome="total_failure").inc()
        return {}

    wait_map = {r["facility_id"]: _wait_info(r) for r in rows}

    try:
        pipe = redis_client.pipeline()
        for r in rows:
            pipe.hset(REDIS_HASH_KEY, r["facility_id"], json.dumps({
                "wait_minutes": r["wait_minutes"],
                "raw_wait": r.get("raw_wait"),
                "predicted": bool(r.get("predicted", False)),
                "source": r.get("source"),
                "updated_at": r.get("recorded_at"),
            }, default=str))
        pipe.execute()
    except Exception:
        logger.warning("redis_populate_failed")

    WAIT_TIMES_CACHE_OUTCOME.labels(outcome="supabase_fallback").inc()
    return wait_map


def get_wait_minutes_map() -> dict[str, int | None]:
    """Minutes only, for the max-wait filter and existing callers."""
    return {fid: info["wait_minutes"] for fid, info in get_wait_map().items()}
