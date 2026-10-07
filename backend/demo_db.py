"""Connection pool for the demo Postgres (role medicoord_app, POSTGRES_DB_URL_APP).

Only services/guest_store.py and the demo branches of services/facilities.py and
services/wait_times.py import this. Every call takes a connection for one statement; the
`with pool.connection()` block commits on success and rolls back on error.
"""
import os
from collections.abc import Mapping, Sequence
from typing import Any

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

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
            max_size=5,
            timeout=5,  # seconds to wait for a free connection
            kwargs={"row_factory": dict_row, "options": "-c statement_timeout=5000"},
            open=True,
        )
    return _pool


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


def fetch_all(sql: str, params: Params = ()) -> list[dict[str, Any]]:
    with open_pool().connection() as conn:
        return conn.execute(sql, params).fetchall()


def fetch_one(sql: str, params: Params = ()) -> dict[str, Any] | None:
    with open_pool().connection() as conn:
        return conn.execute(sql, params).fetchone()


def execute(sql: str, params: Params = ()) -> int:
    with open_pool().connection() as conn:
        return conn.execute(sql, params).rowcount
