import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.chat import (
    create_session, add_message, get_past_conversations, get_older_messages, get_recent_messages,
)


class TestCreateSession:
    @patch("services.chat.supabase_insert")
    def test_inserts_into_sessions_table(self, mock_insert):
        mock_insert.return_value = [{"id": "s1", "user_id": "u1", "title": "hi"}]

        result = create_session("u1", "hi")

        mock_insert.assert_called_once_with("sessions", [{"user_id": "u1", "title": "hi"}])
        assert result == {"id": "s1", "user_id": "u1", "title": "hi"}


class TestAddMessage:
    @patch("services.chat.supabase_insert")
    def test_inserts_into_messages_table(self, mock_insert):
        mock_insert.return_value = [{"id": "m1", "role": "user", "content": "hi"}]

        result = add_message("s1", "u1", "user", "hi")

        mock_insert.assert_called_once_with(
            "messages", [{"session_id": "s1", "user_id": "u1", "role": "user", "content": "hi"}]
        )
        assert result == {"id": "m1", "role": "user", "content": "hi"}


class TestGetPastConversations:
    @patch("services.chat.supabase_select")
    def test_fetches_sessions_then_messages_per_session(self, mock_select):
        def side_effect(table, params, single=False):
            if table == "sessions":
                return [{"id": "s1"}]
            if table == "messages":
                return [{"id": "m2", "created_at": "2"}, {"id": "m1", "created_at": "1"}]
            raise AssertionError(f"unexpected table {table}")

        mock_select.side_effect = side_effect

        sessions, messages = get_past_conversations("u1", session_limit=5, message_limit=20)

        assert sessions == [{"id": "s1"}]
        # messages come back oldest-first (reversed from the desc-ordered query)
        assert messages["s1"] == [{"id": "m1", "created_at": "1"}, {"id": "m2", "created_at": "2"}]

        sessions_call = mock_select.call_args_list[0]
        assert sessions_call.args[0] == "sessions"
        assert sessions_call.args[1]["user_id"] == "eq.u1"
        assert sessions_call.args[1]["order"] == "updated_at.desc"
        assert sessions_call.args[1]["limit"] == "5"


class TestGetOlderMessages:
    @patch("services.chat.supabase_select")
    def test_no_cursor_match_returns_empty_list(self, mock_select):
        mock_select.return_value = None  # cursor lookup found nothing

        result = get_older_messages("s1", "missing-id", limit=20)

        assert result == []

    @patch("services.chat.supabase_select")
    def test_cursor_found_fetches_older_messages(self, mock_select):
        def side_effect(table, params, single=False):
            if single:
                return {"created_at": "2024-01-15T10:00:00"}
            return [{"id": "m1", "created_at": "2024-01-14T10:00:00"}]

        mock_select.side_effect = side_effect

        result = get_older_messages("s1", "before-id", limit=20)

        assert result == [{"id": "m1", "created_at": "2024-01-14T10:00:00"}]
        messages_call = mock_select.call_args_list[1]
        assert messages_call.args[1]["created_at"] == "lt.2024-01-15T10:00:00"


class TestGetRecentMessages:
    @patch("services.chat.supabase_select")
    def test_reads_the_newest_messages_of_the_users_session_oldest_first(self, mock_select, monkeypatch):
        monkeypatch.delenv("DEMO_MODE", raising=False)
        mock_select.return_value = [{"id": "m2", "created_at": "2"}, {"id": "m1", "created_at": "1"}]

        assert get_recent_messages("s1", "u1", limit=7) == [
            {"id": "m1", "created_at": "1"}, {"id": "m2", "created_at": "2"}]

        table, params = mock_select.call_args.args
        assert table == "messages"
        assert params["session_id"] == "eq.s1" and params["user_id"] == "eq.u1"
        assert params["order"] == "created_at.desc" and params["limit"] == "7"

    @patch("services.chat.supabase_select", return_value=None)
    def test_no_rows_is_an_empty_list(self, _mock_select, monkeypatch):
        monkeypatch.delenv("DEMO_MODE", raising=False)
        assert get_recent_messages("s1", "u1") == []

    @patch("services.chat.guest_store.recent_messages", return_value=[{"id": "m1"}])
    def test_demo_mode_reads_the_guest_store(self, mock_recent, monkeypatch):
        monkeypatch.setenv("DEMO_MODE", "true")
        assert get_recent_messages("s1", "g1", limit=5) == [{"id": "m1"}]
        mock_recent.assert_called_once_with("g1", "s1", 5)
