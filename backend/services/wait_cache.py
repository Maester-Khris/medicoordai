"""Wait-time data held in process memory.

A background task reloads it every WAIT_CACHE_TTL_SECONDS plus a random share of that, so
processes started together do not reload together. Request handlers read `current_wait()` and
never call Redis for wait data. A reload that comes back empty keeps the previous copy.
"""
import asyncio
import hashlib
import json
import logging
import random
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone

from starlette.concurrency import run_in_threadpool

from config import env_int
from services.wait_times import get_wait_map, redis_client

logger = logging.getLogger(__name__)

LAST_RUN_KEY = "wait:last_run"  # written by workers/scraper.py after each successful run
WORKER_INTERVAL_SECONDS = 900   # how often the worker runs
JITTER_FRACTION = 0.2


@dataclass(frozen=True)
class WaitSnapshot:
    """`wait_map` has the get_wait_map() shape. `version` changes when the data does."""

    wait_map: dict[str, dict]
    version: str
    last_run: datetime | None


def _version(wait_map: dict[str, dict], last_run: datetime | None) -> str:
    payload = json.dumps(
        [wait_map, last_run.isoformat() if last_run else None], sort_keys=True, default=str
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


_EMPTY = WaitSnapshot({}, _version({}, None), None)
_snapshot: WaitSnapshot = _EMPTY


def current_wait() -> WaitSnapshot:
    return _snapshot


def _read_last_run() -> datetime | None:
    try:
        raw = redis_client.get(LAST_RUN_KEY)
    except Exception as exc:
        logger.warning("wait_last_run_unavailable", extra={"error_type": type(exc).__name__})
        return None
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(str(raw))
    except ValueError:
        logger.warning("wait_last_run_malformed")
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def refresh_once() -> WaitSnapshot:
    """Blocking reload. An empty load is treated as a failed one: the previous copy stays."""
    global _snapshot
    wait_map = get_wait_map()
    if not wait_map and _snapshot.wait_map:
        logger.warning("wait_cache_reload_empty_keeping_previous")
        return _snapshot
    last_run = _read_last_run() or _snapshot.last_run
    _snapshot = WaitSnapshot(wait_map, _version(wait_map, last_run), last_run)
    return _snapshot


def next_delay(rng: Callable[[], float] = random.random) -> float:
    ttl = env_int("WAIT_CACHE_TTL_SECONDS", 30, minimum=1, maximum=WORKER_INTERVAL_SECONDS)
    return ttl * (1 + JITTER_FRACTION * rng())


async def run_forever() -> None:
    """The background reload. Started once by the app's lifespan and cancelled at shutdown."""
    while True:
        await asyncio.sleep(next_delay())
        try:
            await run_in_threadpool(refresh_once)
        except Exception as exc:
            logger.warning("wait_cache_reload_failed", extra={"error_type": type(exc).__name__})


def max_age_seconds(snapshot: WaitSnapshot, now: datetime | None = None) -> int:
    """Seconds a browser may reuse the map data: until the worker's next run, never below the
    floor (the worker can be late) and never above the worker's interval (clocks can differ)."""
    floor = env_int("MAP_MIN_MAX_AGE_SECONDS", 30, minimum=1, maximum=WORKER_INTERVAL_SECONDS)
    if snapshot.last_run is None:
        return floor
    now = now or datetime.now(timezone.utc)
    remaining = WORKER_INTERVAL_SECONDS - int((now - snapshot.last_run).total_seconds())
    return max(floor, min(remaining, WORKER_INTERVAL_SECONDS))


def reset_for_tests() -> None:
    global _snapshot
    _snapshot = _EMPTY
