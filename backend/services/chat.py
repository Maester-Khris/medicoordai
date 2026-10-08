from config import demo_mode
from db import supabase_select, supabase_insert
from services import guest_store


def generate_session_title(first_message: str) -> str:
    title = first_message.strip()
    return title[:50] + ("..." if len(title) > 50 else "")


def create_session(user_id: str, title: str) -> dict:
    if demo_mode():
        return guest_store.create_session(user_id, title)
    rows = supabase_insert("sessions", [{"user_id": user_id, "title": title}])
    return rows[0]


def add_message(session_id: str, user_id: str, role: str, content: str) -> dict:
    if demo_mode():
        return guest_store.add_message(session_id, user_id, role, content)
    rows = supabase_insert("messages", [{
        "session_id": session_id,
        "user_id": user_id,
        "role": role,
        "content": content,
    }])
    return rows[0]


def get_past_conversations(user_id: str, session_limit: int = 5, message_limit: int = 20) -> tuple[list, dict]:
    """
    Returns (sessions_list, messages_dict).
    sessions_list: up to `session_limit` most recent sessions for the user.
    messages_dict: { session_id: [last `message_limit` messages, chronological] }
    """
    if demo_mode():
        return guest_store.get_past_conversations(user_id, session_limit, message_limit)

    sessions = supabase_select("sessions", {
        "select": "*",
        "user_id": f"eq.{user_id}",
        "order": "updated_at.desc",
        "limit": str(session_limit),
    }) or []

    messages: dict[str, list] = {}
    for session in sessions:
        sid = session["id"]
        msgs = supabase_select("messages", {
            "select": "*",
            "session_id": f"eq.{sid}",
            "order": "created_at.desc",
            "limit": str(message_limit),
        }) or []
        messages[sid] = list(reversed(msgs))

    return sessions, messages


def get_older_messages(session_id: str, before_id: str, limit: int = 20, user_id: str | None = None) -> list:
    """
    Cursor-based pagination — returns messages older than `before_id`.
    Always hits the database; older messages are not cached.
    `user_id` scopes the read to the guest in demo mode.
    """
    if demo_mode():
        return guest_store.get_older_messages(user_id or "", session_id, before_id, limit)

    cursor = supabase_select("messages", {"select": "created_at", "id": f"eq.{before_id}"}, single=True)

    if not cursor:
        return []

    cursor_ts = cursor["created_at"]

    msgs = supabase_select("messages", {
        "select": "*",
        "session_id": f"eq.{session_id}",
        "created_at": f"lt.{cursor_ts}",
        "order": "created_at.desc",
        "limit": str(limit),
    }) or []

    return list(reversed(msgs))
