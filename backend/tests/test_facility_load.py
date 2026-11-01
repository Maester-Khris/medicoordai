import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import patch

import pytest

from services import facility_load

FACILITY = {"id": "f1", "category": "hospital", "lat": 43.6596, "lng": -79.3884}
HERE = (43.6532, -79.3832)
NOW = 600_000.0  # minute 10000


@pytest.fixture(autouse=True)
def _clean(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LOAD_AWARE_ROUTING", "on")
    monkeypatch.delenv("LOAD_WINDOW_MINUTES", raising=False)
    facility_load.reset_for_tests()
    yield
    facility_load.reset_for_tests()


def test_a_recommendation_is_counted_under_the_minute_the_facility_and_this_process() -> None:
    with patch("services.facility_load.redis_client") as redis_client, \
         patch("services.facility_load.time.time", return_value=NOW):
        facility_load.record(FACILITY, "routine", *HERE)

    pipe = redis_client.pipeline.return_value
    load_call, spread_call = pipe.hincrby.call_args_list
    assert load_call.args == ("load:10000", f"f1|{facility_load.INSTANCE_ID}", 1)
    key, field, amount = spread_call.args
    assert key == "spread:10000" and amount == 1
    assert field.endswith("|routine|hospital")
    assert [c.args for c in pipe.expire.call_args_list] == [("load:10000", 16 * 60), ("spread:10000", 86400)]
    assert pipe.execute.call_count == 1


def test_this_process_sees_its_own_choice_at_once() -> None:
    with patch("services.facility_load.redis_client"):
        facility_load.record(FACILITY, "routine", *HERE)
        facility_load.record(FACILITY, "routine", *HERE)
    assert facility_load.recent_assignments("f1") == 2
    assert facility_load.recent_assignments("other") == 0


def test_a_failed_write_is_swallowed() -> None:
    with patch("services.facility_load.redis_client") as redis_client:
        redis_client.pipeline.return_value.execute.side_effect = RuntimeError("redis down")
        facility_load.record(FACILITY, "routine", *HERE)  # must not raise
    assert facility_load.recent_assignments("f1") == 1


def test_nothing_is_counted_when_load_aware_routing_is_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOAD_AWARE_ROUTING", "off")
    with patch("services.facility_load.redis_client") as redis_client:
        facility_load.record(FACILITY, "routine", *HERE)
    redis_client.pipeline.assert_not_called()
    assert facility_load.recent_assignments("f1") == 0


def test_recording_from_the_event_loop_still_reaches_redis() -> None:
    with patch("services.facility_load.redis_client") as redis_client:
        async def turn() -> int:
            facility_load.record(FACILITY, "routine", *HERE)
            return facility_load.recent_assignments("f1")

        assert asyncio.run(turn()) == 1  # asyncio.run waits for the executor before returning
    assert redis_client.pipeline.return_value.execute.call_count == 1


def test_a_refresh_sums_the_window_across_processes() -> None:
    with patch("services.facility_load.redis_client") as redis_client, \
         patch("services.facility_load.time.time", return_value=NOW):
        pipe = redis_client.pipeline.return_value
        pipe.execute.return_value = [{}] * 13 + [{"f1|aaa": "2", "f2|aaa": "1"}, {"f1|bbb": "3"}]
        totals = facility_load.refresh_once()

    assert totals == {"f1": 5, "f2": 1}
    assert facility_load.recent_assignments("f1") == 5
    assert [c.args[0] for c in pipe.hgetall.call_args_list] == [f"load:{m}" for m in range(9986, 10001)]


def test_a_refresh_replaces_the_local_count() -> None:
    with patch("services.facility_load.redis_client") as redis_client:
        facility_load.record(FACILITY, "routine", *HERE)
        redis_client.pipeline.return_value.execute.return_value = [{}] * 15
        facility_load.refresh_once()
    assert facility_load.recent_assignments("f1") == 0


def test_a_failed_refresh_keeps_the_previous_counts() -> None:
    with patch("services.facility_load.redis_client") as redis_client:
        redis_client.pipeline.return_value.execute.return_value = [{"f1|aaa": "4"}] + [{}] * 14
        facility_load.refresh_once()
        redis_client.pipeline.return_value.execute.side_effect = RuntimeError("redis down")
        with pytest.raises(RuntimeError):
            facility_load.refresh_once()
    assert facility_load.recent_assignments("f1") == 4


def test_the_next_refresh_is_five_seconds_plus_up_to_twenty_percent() -> None:
    assert facility_load.next_delay(lambda: 0.0) == 5
    assert facility_load.next_delay(lambda: 1.0) == 6
