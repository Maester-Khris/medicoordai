import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import patch

import pytest

from services import chat, facilities, wait_times


@pytest.fixture()
def demo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEMO_MODE", "true")


# ── wait times ────────────────────────────────────────────────────────────────

@patch("services.wait_times.redis_client")
def test_wait_map_reads_predicted_ranges_from_redis(mock_redis) -> None:
    mock_redis.hgetall.return_value = {
        "live": json.dumps({"wait_minutes": 42, "raw_wait": "42 min", "predicted": False}),
        "pred": json.dumps({"wait_minutes": None, "raw_wait": "45m–2h", "predicted": True}),
        "old":  json.dumps({"wait_minutes": 10}),  # written by the old worker: no flags
    }
    assert wait_times.get_wait_map() == {
        "live": {"wait_minutes": 42, "raw_wait": "42 min", "predicted": False},
        "pred": {"wait_minutes": None, "raw_wait": "45m–2h", "predicted": True},
        "old":  {"wait_minutes": 10, "raw_wait": None, "predicted": False},
    }
    assert wait_times.get_wait_minutes_map() == {"live": 42, "pred": None, "old": 10}


@patch("services.wait_times.supabase_rpc")
@patch("services.wait_times.demo_db")
@patch("services.wait_times.redis_client")
def test_demo_fallback_reads_the_table_not_supabase(mock_redis, mock_db, mock_rpc, demo) -> None:
    mock_redis.hgetall.return_value = {}
    mock_db.fetch_all.return_value = [
        {"facility_id": "h1", "wait_minutes": None, "raw_wait": "1h–3h", "predicted": True,
         "source": "erstat", "recorded_at": None},
    ]
    assert wait_times.get_wait_map() == {"h1": {"wait_minutes": None, "raw_wait": "1h–3h", "predicted": True}}
    mock_rpc.assert_not_called()


# ── facilities ────────────────────────────────────────────────────────────────

@patch("services.facilities.demo_db")
def test_demo_facilities_come_from_postgres_with_parsed_hours(mock_db, demo) -> None:
    mock_db.fetch_all.return_value = [
        {"id": "f1", "name": "A", "category": "hospital", "weekday_hours": '["24/7"]'},
        {"id": "f2", "name": "B", "category": "ambulatory", "weekday_hours": None},
    ]
    rows = facilities.get_all_facilities(category="hospital", severity="urgent")
    assert [r["weekday_hours"] for r in rows] == [["24/7"], []]
    sql, params = mock_db.fetch_all.call_args.args
    assert "is_operational" in sql and params == {"category": "hospital", "severity": "urgent"}


@patch("services.facilities.demo_db")
def test_demo_facilities_db_error_is_503(mock_db, demo) -> None:
    from fastapi import HTTPException
    mock_db.fetch_all.side_effect = RuntimeError("down")
    with pytest.raises(HTTPException) as err:
        facilities.get_all_facilities()
    assert err.value.status_code == 503


def test_annotate_wait_details_adds_fields_without_mutating() -> None:
    records = [{"id": "a"}, {"id": "b"}]
    out = facilities.annotate_wait_details(
        records, "id", {"a": {"wait_minutes": None, "raw_wait": "45m–2h", "predicted": True}})
    assert out == [{"id": "a", "raw_wait": "45m–2h", "predicted": True},
                   {"id": "b", "raw_wait": None, "predicted": False}]
    assert records == [{"id": "a"}, {"id": "b"}]


# ── chat ──────────────────────────────────────────────────────────────────────

@patch("services.chat.supabase_insert")
@patch("services.chat.guest_store")
def test_chat_uses_guest_store_in_demo_mode(mock_store, mock_insert, demo) -> None:
    mock_store.create_session.return_value = {"id": "s1"}
    assert chat.create_session("g1", "title") == {"id": "s1"}
    chat.add_message("s1", "g1", "user", "hi")
    chat.get_past_conversations("g1")
    chat.get_older_messages("s1", "m1", user_id="g1")
    mock_store.add_message.assert_called_once_with("s1", "g1", "user", "hi")
    mock_store.get_past_conversations.assert_called_once_with("g1", 5, 20)
    mock_store.get_older_messages.assert_called_once_with("g1", "s1", "m1", 20)
    mock_insert.assert_not_called()


@patch("services.chat.supabase_insert", return_value=[{"id": "s1"}])
@patch("services.chat.guest_store")
def test_chat_uses_supabase_when_flag_off(mock_store, mock_insert, monkeypatch) -> None:
    monkeypatch.delenv("DEMO_MODE", raising=False)
    chat.create_session("u1", "title")
    mock_insert.assert_called_once()
    mock_store.create_session.assert_not_called()
