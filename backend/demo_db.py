"""Connection pool for the demo Postgres (role medicoord_app, POSTGRES_DB_URL_APP).

Only services/guest_store.py and the demo branches of services/facilities.py and
services/wait_times.py import this. Every call takes a connection for one statement; the
`with pool.connection()` block commits on success and rolls back on error.
"""
import logging
import os
from collections.abc import Mapping, Sequence
from typing import Any

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

import metrics
from config import env_int

logger = logging.getLogger(__name__)

Params = Sequence[Any] | Mapping[str, Any]

_pool: ConnectionPool | None = None


def _conninfo() -> str:
    raw = os.environ["POSTGRES_DB_URL_APP"].strip()
    return raw.replace("postgresql+psycopg://", "postgresql://", 1)


def open_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            _conninfo(),
            min_size=1,
            max_size=env_int("DEMO_DB_POOL_MAX", 5, minimum=1, maximum=50),
            # seconds to wait for a free connection
            timeout=env_int("DEMO_DB_POOL_TIMEOUT_SECONDS", 5, minimum=1, maximum=60),
            kwargs={"row_factory": dict_row, "options": "-c statement_timeout=5000"},
            open=True,
        )
    return _pool


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


def pool_stats() -> dict[str, int]:
    """Connections open, in use and callers waiting, for the /metrics gauges. Zeros before the
    pool exists; never raises (a scrape must not fail because the pool is unhealthy)."""
    if _pool is None:
        return {"size": 0, "in_use": 0, "waiting": 0}
    try:
        stats = _pool.get_stats()
    except (RuntimeError, AttributeError, TypeError, ValueError) as exc:
        logger.warning("demo_db_pool_stats_failed", extra={"error_type": type(exc).__name__})
        return {"size": 0, "in_use": 0, "waiting": 0}
    size = int(stats.get("pool_size", 0))
    return {
        "size": size,
        "in_use": size - int(stats.get("pool_available", 0)),
        "waiting": int(stats.get("requests_waiting", 0)),
    }


metrics.bind_pool_stats(pool_stats)


def fetch_all(sql: str, params: Params = ()) -> list[dict[str, Any]]:
    with open_pool().connection() as conn:
        return conn.execute(sql, params).fetchall()


def fetch_one(sql: str, params: Params = ()) -> dict[str, Any] | None:
    with open_pool().connection() as conn:
        return conn.execute(sql, params).fetchone()


def execute(sql: str, params: Params = ()) -> int:
    with open_pool().connection() as conn:
        return conn.execute(sql, params).rowcount
