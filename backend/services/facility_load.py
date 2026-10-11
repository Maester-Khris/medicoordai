"""
Each recommendation increments one Redis hash field; HINCRBY is atomic so processes
need no lock and never wait for one another; every process keeps a local copy of the totals
refreshed in the background and the score reads only that copy, so Redis is never on the path
of a request; a second counter by area, severity and category is written for a later
city-spread view and nothing reads it yet.
"""
import asyncio
import logging
import random
import secrets
import time
from typing import Callable

from starlette.concurrency import run_in_threadpool

import config
from services import cell_index
from services.wait_times import redis_client

logger = logging.getLogger(__name__)

# Unique process instance identifier to partition Redis hash fields without collisions.
INSTANCE_ID: str = secrets.token_hex(6)

# Nominal refresh interval in seconds for the background polling loop.
REFRESH_SECONDS: int = 5

# Local in-memory cache of facility assignment counts across the current load window.
_local_counts: dict[str, int] = {}


def _window_minutes() -> int:
    """Returns the configured rolling load window in minutes, falling back safely to 15."""
    return config.env_int("LOAD_WINDOW_MINUTES", 15, minimum=1, maximum=120)


def record(facility: dict, severity: str, lat: float, lng: float) -> None:
    """
    Records an assigned recommendation both locally and asynchronously in Redis.
    Increments the in-process count immediately for instant local feedback, then
    dispatches an atomic pipeline to Redis without blocking the caller.
    """
    if not config.load_aware_routing():
        return

    facility_id = str(facility["id"])
    _local_counts[facility_id] = _local_counts.get(facility_id, 0) + 1

    minute = int(time.time() // 60)
    window = _window_minutes()
    cell = cell_index.cell_of(lat, lng, 7)
    category = facility.get("category", "")

    def _write_redis() -> None:
        try:
            pipe = redis_client.pipeline()
            pipe.hincrby(f"load:{minute}", f"{facility_id}|{INSTANCE_ID}", 1)
            pipe.expire(f"load:{minute}", (window + 1) * 60)
            pipe.hincrby(f"spread:{minute}", f"{cell}|{severity}|{category}", 1)
            pipe.expire(f"spread:{minute}", 86400)
            pipe.execute()
        except Exception as exc:
            logger.warning(
                "facility_load_write_failed",
                extra={"error_type": type(exc).__name__},
            )

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is not None and loop.is_running():
        loop.run_in_executor(None, _write_redis)
    else:
        _write_redis()


def recent_assignments(facility_id: str) -> int:
    """
    Returns the number of recent recommendations assigned to the given facility
    from the in-memory cache, keeping the hot request path entirely off Redis.
    """
    return _local_counts.get(str(facility_id), 0)


def refresh_once(now: float | None = None) -> dict[str, int]:
    """
    Fetches assignment tallies across all processes for the rolling load window from Redis,
    aggregating by facility ID and atomically replacing the local cache. Redis errors
    propagate upward and preserve the existing local totals.
    """
    global _local_counts
    current_time = time.time() if now is None else now
    current_minute = int(current_time // 60)
    window = _window_minutes()
    start_minute = current_minute - window + 1

    pipe = redis_client.pipeline()
    for m in range(start_minute, current_minute + 1):
        pipe.hgetall(f"load:{m}")
    results = pipe.execute()

    totals: dict[str, int] = {}
    for minute_dict in results:
        if not minute_dict:
            continue
        for field, count_val in minute_dict.items():
            fac_id = field.split("|", 1)[0]
            totals[fac_id] = totals.get(fac_id, 0) + int(count_val)

    _local_counts = totals
    return totals


def next_delay(rng: Callable[[], float] = random.random) -> float:
    """
    Computes a jittered refresh interval to prevent thundering herd behavior
    when multiple worker processes poll Redis concurrently.
    """
    return REFRESH_SECONDS * (1 + 0.2 * rng())


async def run_forever() -> None:
    """
    Background polling loop refreshing local facility load counters from Redis.
    Periodically pulls cross-process totals, skipping execution when load-aware
    routing is turned off and logging any transient network or Redis failures.
    """
    while True:
        await asyncio.sleep(next_delay())
        if not config.load_aware_routing():
            continue
        try:
            await run_in_threadpool(refresh_once)
        except Exception as exc:
            logger.warning(
                "facility_load_refresh_failed",
                extra={"error_type": type(exc).__name__},
            )


def reset_for_tests() -> None:
    """Resets the in-memory counter state between test executions."""
    global _local_counts
    _local_counts = {}
