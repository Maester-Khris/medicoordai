import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import MagicMock, patch

import pytest

import demo_db


@pytest.fixture(autouse=True)
def _no_pool(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(demo_db, "_pool", None)
    monkeypatch.setenv("POSTGRES_DB_URL_APP", "postgresql://u:p@localhost:1/db")
    yield
    monkeypatch.setattr(demo_db, "_pool", None)


def _open_with_fake_pool() -> dict:
    with patch.object(demo_db, "ConnectionPool") as pool_class:
        demo_db.open_pool()
    return pool_class.call_args.kwargs


def test_pool_uses_the_defaults_when_nothing_is_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEMO_DB_POOL_MAX", raising=False)
    monkeypatch.delenv("DEMO_DB_POOL_TIMEOUT_SECONDS", raising=False)
    kwargs = _open_with_fake_pool()
    assert (kwargs["min_size"], kwargs["max_size"], kwargs["timeout"]) == (1, 5, 5)


def test_pool_size_and_timeout_come_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEMO_DB_POOL_MAX", "12")
    monkeypatch.setenv("DEMO_DB_POOL_TIMEOUT_SECONDS", "2")
    kwargs = _open_with_fake_pool()
    assert (kwargs["max_size"], kwargs["timeout"]) == (12, 2)


@pytest.mark.parametrize("bad", ["0", "-3", "51", "many", ""])
def test_an_invalid_pool_size_falls_back_to_the_default(monkeypatch: pytest.MonkeyPatch, bad: str) -> None:
    monkeypatch.setenv("DEMO_DB_POOL_MAX", bad)
    assert _open_with_fake_pool()["max_size"] == 5


def test_pool_stats_are_zero_before_the_pool_exists() -> None:
    assert demo_db.pool_stats() == {"size": 0, "in_use": 0, "waiting": 0}


def test_pool_stats_come_from_the_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    pool = MagicMock()
    pool.get_stats.return_value = {"pool_size": 5, "pool_available": 2, "requests_waiting": 3}
    monkeypatch.setattr(demo_db, "_pool", pool)
    assert demo_db.pool_stats() == {"size": 5, "in_use": 3, "waiting": 3}


def test_pool_stats_never_raise(monkeypatch: pytest.MonkeyPatch) -> None:
    pool = MagicMock()
    pool.get_stats.side_effect = RuntimeError("pool closed")
    monkeypatch.setattr(demo_db, "_pool", pool)
    assert demo_db.pool_stats() == {"size": 0, "in_use": 0, "waiting": 0}
