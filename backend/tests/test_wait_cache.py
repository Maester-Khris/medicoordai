import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from services import wait_cache
from services.wait_cache import WaitSnapshot

INFO_A = {"a": {"wait_minutes": 10, "raw_wait": None, "predicted": False}}
INFO_B = {"b": {"wait_minutes": 20, "raw_wait": None, "predicted": False}}
T0 = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _clean():
    wait_cache.reset_for_tests()
    yield
    wait_cache.reset_for_tests()


def _refresh(wait_map: dict, last_run_raw: object) -> WaitSnapshot:
    with patch("services.wait_cache.get_wait_map", return_value=wait_map), \
         patch("services.wait_cache.redis_client") as redis_client:
        redis_client.get.return_value = last_run_raw
        return wait_cache.refresh_once()


def test_before_any_load_the_copy_is_empty() -> None:
    snapshot = wait_cache.current_wait()
    assert snapshot.wait_map == {} and snapshot.last_run is None


def test_a_refresh_replaces_the_copy_and_reads_the_last_run() -> None:
    _refresh(INFO_A, T0.isoformat())
    snapshot = wait_cache.current_wait()
    assert snapshot.wait_map == INFO_A and snapshot.last_run == T0


def test_the_version_changes_with_the_data_and_only_with_the_data() -> None:
    first = _refresh(INFO_A, T0.isoformat()).version
    assert _refresh(INFO_A, T0.isoformat()).version == first
    second = _refresh(INFO_B, T0.isoformat()).version
    assert second != first
    assert _refresh(INFO_B, (T0 + timedelta(minutes=15)).isoformat()).version != second


def test_an_empty_reload_keeps_the_previous_copy() -> None:
    before = _refresh(INFO_A, T0.isoformat())
    assert _refresh({}, None) is before
    assert wait_cache.current_wait().wait_map == INFO_A


def test_a_missing_or_malformed_last_run_keeps_the_previous_one() -> None:
    _refresh(INFO_A, T0.isoformat())
    assert _refresh(INFO_B, None).last_run == T0
    assert _refresh(INFO_A, "not a date").last_run == T0


def test_a_redis_error_on_the_last_run_does_not_fail_the_refresh() -> None:
    with patch("services.wait_cache.get_wait_map", return_value=INFO_A), \
         patch("services.wait_cache.redis_client") as redis_client:
        redis_client.get.side_effect = RuntimeError("redis down")
        snapshot = wait_cache.refresh_once()
    assert snapshot.wait_map == INFO_A and snapshot.last_run is None


def test_a_timestamp_without_a_zone_is_read_as_utc() -> None:
    assert _refresh(INFO_A, "2026-10-10T12:00:00").last_run == T0


def test_the_next_delay_is_the_ttl_plus_up_to_twenty_percent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WAIT_CACHE_TTL_SECONDS", "30")
    assert wait_cache.next_delay(lambda: 0.0) == 30
    assert wait_cache.next_delay(lambda: 1.0) == 36


def test_max_age_counts_down_to_the_next_run(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MAP_MIN_MAX_AGE_SECONDS", raising=False)
    snapshot = WaitSnapshot(INFO_A, "v", T0)
    assert wait_cache.max_age_seconds(snapshot, now=T0 + timedelta(minutes=5)) == 600


def test_max_age_never_goes_below_the_floor(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MAP_MIN_MAX_AGE_SECONDS", raising=False)
    snapshot = WaitSnapshot(INFO_A, "v", T0)
    assert wait_cache.max_age_seconds(snapshot, now=T0 + timedelta(minutes=14, seconds=50)) == 30
    assert wait_cache.max_age_seconds(snapshot, now=T0 + timedelta(hours=1)) == 30


def test_max_age_is_the_floor_without_a_last_run(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAP_MIN_MAX_AGE_SECONDS", "45")
    assert wait_cache.max_age_seconds(WaitSnapshot(INFO_A, "v", None), now=T0) == 45


def test_max_age_is_capped_at_the_worker_interval(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MAP_MIN_MAX_AGE_SECONDS", raising=False)
    snapshot = WaitSnapshot(INFO_A, "v", T0)
    assert wait_cache.max_age_seconds(snapshot, now=T0 - timedelta(minutes=5)) == 900
