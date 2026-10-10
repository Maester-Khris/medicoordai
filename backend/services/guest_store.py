"""All SQL for guest data in the demo Postgres.

Every statement that touches a session or a message carries the guest id: the backend connects
as one database role, so this module is what keeps one guest out of another guest's data.
Ids are returned as text and `guest_id` is exposed as `user_id`, so rows match the API contract
(`Session` / `Message` in shared/types.ts) the Supabase path already serves.
"""
from uuid import UUID

import demo_db

SESSION_COLUMNS = "id::text as id, guest_id::text as user_id, title, created_at, updated_at"
MESSAGE_COLUMNS = (
    "id::text as id, session_id::text as session_id, guest_id::text as user_id, "
    "role, content, created_at"
)
RETENTION_DAYS = 30


class SessionNotFound(LookupError):
    """The session does not exist or belongs to another guest."""


def _is_uuid(value: str) -> bool:
    try:
        UUID(str(value))
    except ValueError:
        return False
    return True


def touch_guest(guest_id: str, internal: bool) -> bool:
    row = demo_db.fetch_one(
        """
        insert into guests (id, is_internal) values (%s, %s)
        on conflict (id) do update
            set last_seen_at = now(),
                is_internal = guests.is_internal or excluded.is_internal
        returning (xmax = 0) as created
        """,
        (guest_id, internal),
    )
    return bool(row and row["created"])


def create_session(guest_id: str, title: str) -> dict:
    row = demo_db.fetch_one(
        f"insert into sessions (guest_id, title) values (%s, %s) returning {SESSION_COLUMNS}",
        (guest_id, title),
    )
    assert row is not None  # insert ... returning always yields the row
    return row


def add_message(session_id: str, guest_id: str, role: str, content: str) -> dict:
    if not _is_uuid(session_id):
        raise SessionNotFound(session_id)
    # one statement: the insert happens only if the session belongs to this guest
    row = demo_db.fetch_one(
        f"""
        with owned as (
            update sessions set updated_at = now()
            where id = %s and guest_id = %s
            returning id
        )
        insert into messages (session_id, guest_id, role, content)
        select id, %s, %s, %s from owned
        returning {MESSAGE_COLUMNS}
        """,
        (session_id, guest_id, guest_id, role, content),
    )
    if row is None:
        raise SessionNotFound(session_id)
    return row


def get_past_conversations(
    guest_id: str, session_limit: int = 5, message_limit: int = 20
) -> tuple[list[dict], dict[str, list[dict]]]:
    sessions = demo_db.fetch_all(
        f"select {SESSION_COLUMNS} from sessions where guest_id = %s "
        "order by updated_at desc limit %s",
        (guest_id, session_limit),
    )
    if not sessions:
        return [], {}

    session_ids = [s["id"] for s in sessions]
    rows = demo_db.fetch_all(
        f"""
        select id, session_id, user_id, role, content, created_at from (
            select {MESSAGE_COLUMNS},
                   row_number() over (partition by session_id order by created_at desc) as rn
            from messages
            where session_id = any(%s::uuid[]) and guest_id = %s
        ) newest
        where rn <= %s
        order by created_at
        """,
        (session_ids, guest_id, message_limit),
    )
    messages: dict[str, list[dict]] = {sid: [] for sid in session_ids}
    for row in rows:
        messages[row["session_id"]].append(row)
    return sessions, messages


def get_older_messages(guest_id: str, session_id: str, before_id: str, limit: int = 20) -> list[dict]:
    if not (_is_uuid(guest_id) and _is_uuid(session_id) and _is_uuid(before_id)):
        return []
    rows = demo_db.fetch_all(
        f"""
        select {MESSAGE_COLUMNS} from messages
        where session_id = %s and guest_id = %s
          and created_at < (select created_at from messages where id = %s and guest_id = %s)
        order by created_at desc
        limit %s
        """,
        (session_id, guest_id, before_id, guest_id, limit),
    )
    return list(reversed(rows))


def upsert_feedback(guest_id: str, session_id: str, message_id: str, thumb: str, comment: str | None) -> bool:
    written = demo_db.execute(
        """
        insert into feedback (guest_id, session_id, message_id, thumb, comment)
        select guest_id, session_id, id, %s, %s from messages
        where id = %s and session_id = %s and guest_id = %s and role = 'assistant'
        on conflict (message_id) do update
            set thumb = excluded.thumb, comment = excluded.comment, updated_at = now()
        """,
        (thumb, comment, message_id, session_id, guest_id),
    )
    return written > 0


def record_event(
    guest_id: str,
    event_type: str,
    session_id: str,
    mode: str | None = None,
    duration_ms: int | None = None,
) -> bool:
    if not _is_uuid(session_id):
        return False
    owned = demo_db.fetch_one(
        "select 1 as ok from sessions where id = %s and guest_id = %s", (session_id, guest_id)
    )
    if owned is None:
        return False
    # the conflict target must repeat the predicate of the partial unique index (revision 0005)
    demo_db.execute(
        """
        insert into events (guest_id, session_id, type, mode, duration_ms) values (%s, %s, %s, %s, %s)
        on conflict (session_id, type) where session_id is not null and type <> 'mode_changed' do nothing
        """,
        (guest_id, session_id, event_type, mode, duration_ms),
    )
    return True


def purge_expired_sessions() -> int:
    """Chat text retention: a session (title and messages) lives 30 days from its creation."""
    return demo_db.execute(
        "delete from sessions where created_at < now() - make_interval(days => %s)", (RETENTION_DAYS,)
    )
