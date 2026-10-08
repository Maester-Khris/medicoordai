"""guest_store against the local rehearsal DB (docker medicoord-demo-pg, revision 0004).

Never touches the remote database: POSTGRES_DB_URL_APP is forced to the local DSN.
Skipped when the container is not running.
"""
import os
import sys
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import psycopg
import pytest

import demo_db
from services import guest_store

LOCAL_DSN = "postgresql://postgres:postgres@localhost:5433/medicoord_demo"


@pytest.fixture()
def guest(monkeypatch: pytest.MonkeyPatch):
    try:
        admin = psycopg.connect(LOCAL_DSN, connect_timeout=3, autocommit=True)
    except psycopg.OperationalError:
        pytest.skip("local rehearsal DB not running")
    monkeypatch.setenv("POSTGRES_DB_URL_APP", LOCAL_DSN)
    demo_db.close_pool()
    created: list[str] = []

    def make() -> str:
        gid = str(uuid.uuid4())
        guest_store.touch_guest(gid, internal=False)
        created.append(gid)
        return gid

    yield make
    demo_db.close_pool()
    admin.execute("delete from events where guest_id = any(%s::uuid[])", (created,))
    admin.execute("delete from guests where id = any(%s::uuid[])", (created,))
    admin.execute("delete from sessions where title like 'pytest-%'")
    admin.close()


def test_touch_guest_reports_creation_once(guest) -> None:
    gid = str(uuid.uuid4())
    try:
        assert guest_store.touch_guest(gid, internal=False) is True
        assert guest_store.touch_guest(gid, internal=False) is False
    finally:
        with psycopg.connect(LOCAL_DSN, autocommit=True) as admin:
            admin.execute("delete from guests where id = %s", (gid,))


def test_internal_flag_sticks_once_set(guest) -> None:
    gid = guest()
    guest_store.touch_guest(gid, internal=True)
    guest_store.touch_guest(gid, internal=False)
    row = demo_db.fetch_one("select is_internal from guests where id = %s", (gid,))
    assert row == {"is_internal": True}


def test_session_and_messages_round_trip_with_string_ids(guest) -> None:
    gid = guest()
    session = guest_store.create_session(gid, "pytest-fever")
    assert session["user_id"] == gid and isinstance(session["id"], str)

    user_msg = guest_store.add_message(session["id"], gid, "user", "I have a fever")
    guest_store.add_message(session["id"], gid, "assistant", "How long?")
    assert user_msg["user_id"] == gid and user_msg["session_id"] == session["id"]

    sessions, messages = guest_store.get_past_conversations(gid)
    assert [s["id"] for s in sessions] == [session["id"]]
    assert [m["content"] for m in messages[session["id"]]] == ["I have a fever", "How long?"]


def test_add_message_rejects_foreign_session(guest) -> None:
    owner, intruder = guest(), guest()
    session = guest_store.create_session(owner, "pytest-private")
    with pytest.raises(guest_store.SessionNotFound):
        guest_store.add_message(session["id"], intruder, "user", "let me in")
    assert demo_db.fetch_one("select count(*) as n from messages where session_id = %s",
                             (session["id"],)) == {"n": 0}


@pytest.mark.parametrize("bad", ["", "abc", "1; drop table guests", "00000000-0000"])
def test_add_message_bad_session_id_is_not_found(guest, bad: str) -> None:
    with pytest.raises(guest_store.SessionNotFound):
        guest_store.add_message(bad, guest(), "user", "x")


def test_past_conversations_only_returns_own_sessions(guest) -> None:
    a, b = guest(), guest()
    guest_store.create_session(a, "pytest-a")
    assert guest_store.get_past_conversations(b) == ([], {})


def test_message_limit_keeps_the_newest_in_order(guest) -> None:
    gid = guest()
    session = guest_store.create_session(gid, "pytest-limit")
    for i in range(5):
        guest_store.add_message(session["id"], gid, "user", f"m{i}")
    _, messages = guest_store.get_past_conversations(gid, message_limit=2)
    assert [m["content"] for m in messages[session["id"]]] == ["m3", "m4"]


def test_older_messages_are_paginated_and_owned(guest) -> None:
    owner, intruder = guest(), guest()
    session = guest_store.create_session(owner, "pytest-older")
    ids = [guest_store.add_message(session["id"], owner, "user", f"m{i}")["id"] for i in range(3)]
    older = guest_store.get_older_messages(owner, session["id"], ids[2])
    assert [m["content"] for m in older] == ["m0", "m1"]
    assert guest_store.get_older_messages(intruder, session["id"], ids[2]) == []


def test_older_messages_bad_uuid_is_empty(guest) -> None:
    assert guest_store.get_older_messages(guest(), "nope", "nope") == []


def test_feedback_upserts_one_row_per_message(guest) -> None:
    gid = guest()
    session = guest_store.create_session(gid, "pytest-feedback")
    guest_store.add_message(session["id"], gid, "user", "hi")
    reply = guest_store.add_message(session["id"], gid, "assistant", "Go to X")

    assert guest_store.upsert_feedback(gid, session["id"], reply["id"], "up", None) is True
    assert guest_store.upsert_feedback(gid, session["id"], reply["id"], "down", "wrong place") is True
    rows = demo_db.fetch_all("select thumb, comment from feedback where message_id = %s", (reply["id"],))
    assert rows == [{"thumb": "down", "comment": "wrong place"}]


def test_feedback_rejects_foreign_message(guest) -> None:
    owner, intruder = guest(), guest()
    session = guest_store.create_session(owner, "pytest-fb-foreign")
    reply = guest_store.add_message(session["id"], owner, "assistant", "Go to X")
    assert guest_store.upsert_feedback(intruder, session["id"], reply["id"], "up", None) is False


def test_feedback_rejects_user_messages(guest) -> None:
    gid = guest()
    session = guest_store.create_session(gid, "pytest-fb-user")
    msg = guest_store.add_message(session["id"], gid, "user", "hi")
    assert guest_store.upsert_feedback(gid, session["id"], msg["id"], "up", None) is False


def test_event_is_recorded_once_per_session_and_type(guest) -> None:
    gid = guest()
    session = guest_store.create_session(gid, "pytest-event")
    assert guest_store.record_event(gid, "route_drawn", session["id"]) is True
    assert guest_store.record_event(gid, "route_drawn", session["id"]) is True
    assert demo_db.fetch_one("select count(*) as n from events where session_id = %s",
                             (session["id"],)) == {"n": 1}


def test_event_rejects_foreign_session(guest) -> None:
    owner, intruder = guest(), guest()
    session = guest_store.create_session(owner, "pytest-event-foreign")
    assert guest_store.record_event(intruder, "route_drawn", session["id"]) is False


def test_purge_deletes_sessions_older_than_30_days_and_keeps_feedback(guest) -> None:
    gid = guest()
    old = guest_store.create_session(gid, "pytest-old")
    new = guest_store.create_session(gid, "pytest-new")
    reply = guest_store.add_message(old["id"], gid, "assistant", "Go to X")
    guest_store.upsert_feedback(gid, old["id"], reply["id"], "up", None)
    with psycopg.connect(LOCAL_DSN, autocommit=True) as admin:
        admin.execute("update sessions set created_at = now() - interval '31 days' where id = %s", (old["id"],))

    assert guest_store.purge_expired_sessions() >= 1

    remaining = demo_db.fetch_all("select id::text as id from sessions where guest_id = %s", (gid,))
    assert remaining == [{"id": new["id"]}]
    assert demo_db.fetch_one("select count(*) as n from messages where session_id = %s", (old["id"],)) == {"n": 0}
    assert demo_db.fetch_one("select count(*) as n from feedback where message_id = %s", (reply["id"],)) == {"n": 1}


def test_route_drawn_stores_its_mode(guest) -> None:
    gid = guest()
    session = guest_store.create_session(gid, "pytest-event-mode")
    assert guest_store.record_event(gid, "route_drawn", session["id"], "bike") is True
    row = demo_db.fetch_one(
        "select mode, duration_ms from events where session_id = %s and type = 'route_drawn'", (session["id"],)
    )
    assert row == {"mode": "bike", "duration_ms": None}


def test_mode_changed_repeats_but_route_drawn_does_not(guest) -> None:
    gid = guest()
    session = guest_store.create_session(gid, "pytest-event-repeat")
    guest_store.record_event(gid, "route_drawn", session["id"], "car")
    guest_store.record_event(gid, "route_drawn", session["id"], "bike")
    guest_store.record_event(gid, "mode_changed", session["id"], "bike", 900)
    guest_store.record_event(gid, "mode_changed", session["id"], "walk", 450)
    rows = demo_db.fetch_all(
        "select type, mode, duration_ms from events where session_id = %s order by id", (session["id"],)
    )
    assert rows == [
        {"type": "route_drawn", "mode": "car", "duration_ms": None},
        {"type": "mode_changed", "mode": "bike", "duration_ms": 900},
        {"type": "mode_changed", "mode": "walk", "duration_ms": 450},
    ]
