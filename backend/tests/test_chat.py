"""
Unit tests for chat logic, serialisation, cache, and endpoints.
All Supabase calls are mocked — no env vars or network required.
"""

import os
import sys

# Ensure backend/ is on sys.path regardless of how pytest is invoked
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import datetime, date
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from services.chat import generate_session_title
from routers.chat import _ser, router as chat_router
from middleware.auth import get_current_user, get_actor

# ── Shared test fixtures ──────────────────────────────────────────────────────

FAKE_USER_ID = UUID("00000000-0000-0000-0000-000000000001")
FAKE_USER_ID_STR = str(FAKE_USER_ID)
FAKE_SESSION_ID = "00000000-0000-0000-0000-000000000002"


class _FakeUser:
    id = FAKE_USER_ID
    email = "test@example.com"
    is_guest = False


def _make_test_app(authenticated: bool = True) -> FastAPI:
    app = FastAPI()
    if authenticated:
        app.dependency_overrides[get_actor] = lambda: _FakeUser()
    app.include_router(chat_router)
    return app


@pytest.fixture(autouse=True)
def _turn_defaults():
    """Every test gets an empty history and an agent that asks a follow-up question.
    A test overrides either with its own patch; the history mock is what the fixture yields."""
    agent = MagicMock()
    agent.respond = AsyncMock(return_value={
        "response": "Can you tell me more?", "severity": None, "reasoning": None,
        "recommended_facility": None, "nearby_facilities": [], "turn_type": "followup",
    })
    with patch("routers.chat.get_recent_messages", return_value=[]) as history, \
         patch("routers.chat.get_agent", return_value=agent):
        yield history


# ── 1. generate_session_title ─────────────────────────────────────────────────

class TestGenerateSessionTitle:
    def test_exactly_50_chars_no_ellipsis(self):
        msg = "a" * 50
        assert generate_session_title(msg) == "a" * 50

    def test_51_chars_truncated_with_ellipsis(self):
        msg = "a" * 51
        assert generate_session_title(msg) == "a" * 50 + "..."

    def test_shorter_than_50_returned_as_is(self):
        assert generate_session_title("hello") == "hello"

    def test_leading_trailing_whitespace_stripped_before_truncation(self):
        msg = "  " + "a" * 50 + "  "
        assert generate_session_title(msg) == "a" * 50

    def test_empty_string_returns_empty(self):
        assert generate_session_title("") == ""


# ── 2. _ser (serialize_for_json) ──────────────────────────────────────────────

class TestSer:
    def test_dict_with_datetime_value(self):
        dt = datetime(2024, 1, 15, 10, 30, 0)
        assert _ser({"created_at": dt}) == {"created_at": "2024-01-15T10:30:00"}

    def test_nested_dict_with_datetime_all_converted(self):
        dt = datetime(2024, 1, 15, 10, 30, 0)
        result = _ser({"session": {"created_at": dt, "title": "test"}})
        assert result == {"session": {"created_at": "2024-01-15T10:30:00", "title": "test"}}

    def test_list_of_dicts_with_datetimes_all_converted(self):
        dt = datetime(2024, 1, 15, 10, 30, 0)
        result = _ser([{"created_at": dt}, {"created_at": dt}])
        assert result == [
            {"created_at": "2024-01-15T10:30:00"},
            {"created_at": "2024-01-15T10:30:00"},
        ]

    def test_dict_without_datetimes_returned_unchanged(self):
        data = {"id": "abc", "title": "test", "count": 5}
        assert _ser(data) == data

    def test_date_object_also_converted(self):
        d = date(2024, 1, 15)
        assert _ser({"day": d}) == {"day": "2024-01-15"}


# ── 4. GET /chat/sessions ─────────────────────────────────────────────────────

_FAKE_SESSION_DICT = {
    "id": FAKE_SESSION_ID,
    "user_id": FAKE_USER_ID_STR,
    "title": "Test session",
    "created_at": "2024-01-15T10:00:00",
    "updated_at": "2024-01-15T10:00:00",
}


class TestGetSessions:
    @pytest.fixture
    def client(self):
        return TestClient(_make_test_app(authenticated=True))

    @pytest.fixture
    def raw_client(self):
        """Client with no dependency override — real get_current_user runs."""
        return TestClient(_make_test_app(authenticated=False))

    def test_malformed_auth_header_returns_401(self, raw_client):
        # "not-bearer" does not start with "Bearer " → HTTPException(401)
        resp = raw_client.get("/chat/sessions", headers={"Authorization": "not-bearer"})
        assert resp.status_code == 401

    def test_invalid_token_returns_401(self, raw_client):
        with patch("middleware.auth.verify_token", side_effect=HTTPException(401, "bad token")):
            resp = raw_client.get(
                "/chat/sessions", headers={"Authorization": "Bearer invalid"}
            )
        assert resp.status_code == 401

    def test_valid_auth_cold_cache_returns_200_with_etag(self, client):
        with patch("routers.chat.get_past_conversations", return_value=([_FAKE_SESSION_DICT], {})):
            resp = client.get("/chat/sessions")
        assert resp.status_code == 200
        assert "ETag" in resp.headers

    def test_matching_if_none_match_returns_304(self, client):
        with patch("routers.chat.get_past_conversations", return_value=([], {})):
            resp1 = client.get("/chat/sessions")
            etag = resp1.headers["ETag"]
            resp2 = client.get("/chat/sessions", headers={"If-None-Match": etag})
        assert resp2.status_code == 304

    def test_different_if_none_match_returns_200(self, client):
        with patch("routers.chat.get_past_conversations", return_value=([], {})):
            resp = client.get("/chat/sessions", headers={"If-None-Match": '"stale"'})
        assert resp.status_code == 200

    def test_response_body_has_no_datetime_objects(self, client):
        session_with_dt = {**_FAKE_SESSION_DICT, "created_at": datetime(2024, 1, 15, 10, 0, 0)}
        with patch("routers.chat.get_past_conversations", return_value=([session_with_dt], {})):
            resp = client.get("/chat/sessions")
        assert resp.status_code == 200
        for session in resp.json()["sessions"]:
            for val in session.values():
                assert not isinstance(val, datetime)


# ── 5. POST /chat/message ─────────────────────────────────────────────────────

class TestSendMessage:
    def _fake_msg(self, role: str, content: str) -> dict:
        return {
            "id": "00000000-0000-0000-0000-000000000003",
            "session_id": FAKE_SESSION_ID,
            "user_id": FAKE_USER_ID_STR,
            "role": role,
            "content": content,
            "created_at": "2024-01-15T10:00:00",
        }

    def _post(self, client: TestClient, content: str):
        return client.post(
            "/chat/message",
            json={"session_id": FAKE_SESSION_ID, "content": content},
        )

    @pytest.fixture
    def client(self):
        return TestClient(_make_test_app(authenticated=True))

    @pytest.fixture
    def raw_client(self):
        return TestClient(_make_test_app(authenticated=False))

    def test_invalid_token_returns_401(self, raw_client):
        with patch("middleware.auth.verify_token", side_effect=HTTPException(401, "bad")):
            resp = raw_client.post(
                "/chat/message",
                headers={"Authorization": "Bearer bad"},
                json={"session_id": FAKE_SESSION_ID, "content": "hello"},
            )
        assert resp.status_code == 401

    def test_short_content_no_ellipsis_in_assistant_reply(self, client):
        user_msg = self._fake_msg("user", "hello")
        assistant_msg = self._fake_msg("assistant", "hello")
        with patch("routers.chat.add_message", side_effect=[user_msg, assistant_msg]):
            resp = self._post(client, "hello")
        assert resp.status_code == 200
        assert resp.json()["assistant_message"]["content"] == "hello"

    def test_send_message_calls_llm_agent_and_returns_response(self, client):
        """LLMAgent.respond is called and its response is used as assistant content."""
        from unittest.mock import patch, MagicMock

        user_msg = self._fake_msg("user", "I have a headache")
        assistant_msg = self._fake_msg("assistant", "Can you tell me more?")

        with patch("routers.chat.add_message", side_effect=[user_msg, assistant_msg]), \
             patch("routers.chat.get_agent") as MockAgent:
            mock_instance = MagicMock()
            mock_instance.respond = AsyncMock(return_value={
                "response": "Can you tell me more?",
                "severity": None,
                "reasoning": None,
                "recommended_facility": None,
                "nearby_facilities": [],
                "turn_type": "followup",
            })
            MockAgent.return_value = mock_instance
            resp = self._post(client, "I have a headache")

        assert resp.status_code == 200
        data = resp.json()
        assert data["assistant_message"]["content"] == "Can you tell me more?"
        assert data["triage"] is None

    def test_send_message_returns_triage_on_classification(self, client):
        """When LLMAgent returns turn_type=triage, response includes triage object."""
        from unittest.mock import patch, MagicMock

        user_msg = self._fake_msg("user", "chest pain")
        assistant_msg = self._fake_msg("assistant", "Go to Toronto General immediately.")

        fake_facility = {
            "id": "fac-001", "name": "Toronto General Hospital",
            "category": "hospital", "address": "200 Elizabeth St",
            "lat": 43.659, "lng": -79.388, "distanceKm": 1.2,
        }

        with patch("routers.chat.add_message", side_effect=[user_msg, assistant_msg]), \
             patch("routers.chat.get_agent") as MockAgent:
            mock_instance = MagicMock()
            mock_instance.respond = AsyncMock(return_value={
                "response": "Go to Toronto General immediately.",
                "severity": "emergent",
                "reasoning": "Chest pain may indicate cardiac event.",
                "recommended_facility": fake_facility,
                "nearby_facilities": [],
                "turn_type": "triage",
            })
            MockAgent.return_value = mock_instance
            resp = self._post(client, "chest pain")

        assert resp.status_code == 200
        data = resp.json()
        assert data["triage"] is not None
        assert data["triage"]["severity"] == "emergent"
        assert data["triage"]["recommended_facility"]["name"] == "Toronto General Hospital"

    def test_llm_agent_failure_returns_safe_fallback(self, client):
        """When LLMAgent raises, endpoint returns 200 with safe error message."""
        from unittest.mock import patch, MagicMock

        user_msg = self._fake_msg("user", "I feel sick")
        fallback_msg = self._fake_msg("assistant",
            "I'm having trouble processing your request right now. "
            "If this is an emergency, please call 911.")

        with patch("routers.chat.add_message", side_effect=[user_msg, fallback_msg]), \
             patch("routers.chat.get_agent") as MockAgent:
            MockAgent.return_value.respond = AsyncMock(side_effect=Exception("LLM unavailable"))
            resp = self._post(client, "I feel sick")

        assert resp.status_code == 200
        data = resp.json()
        assert "911" in data["assistant_message"]["content"]
        assert data["triage"] is None

    def test_response_contains_both_user_and_assistant_messages(self, client):
        user_msg = self._fake_msg("user", "hi")
        assistant_msg = self._fake_msg("assistant", "hi")
        with patch("routers.chat.add_message", side_effect=[user_msg, assistant_msg]):
            resp = self._post(client, "hi")
        body = resp.json()
        assert "user_message" in body
        assert "assistant_message" in body


class TestSendMessageRoutingShadowDispatch:
    def _fake_msg(self, role: str, content: str) -> dict:
        return {
            "id": "00000000-0000-0000-0000-000000000003",
            "session_id": FAKE_SESSION_ID,
            "user_id": FAKE_USER_ID_STR,
            "role": role,
            "content": content,
            "created_at": "2024-01-15T10:00:00",
        }

    @pytest.fixture
    def client(self):
        return TestClient(_make_test_app(authenticated=True))

    def test_shadow_call_dispatched_when_sampled_and_facility_present(self, client):
        user_msg = self._fake_msg("user", "chest pain")
        assistant_msg = self._fake_msg("assistant", "Go to Toronto General immediately.")
        fake_facility = {
            "id": "fac-001", "name": "Toronto General Hospital",
            "category": "hospital", "address": "200 Elizabeth St",
            "lat": 43.659, "lng": -79.388, "distanceKm": 1.2,
        }

        with patch("routers.chat.add_message", side_effect=[user_msg, assistant_msg]), \
             patch("routers.chat.get_agent") as MockAgent, \
             patch("routers.chat.should_sample", return_value=True), \
             patch("routers.chat.log_routing_comparison") as mock_log:
            mock_instance = MagicMock()
            mock_instance.respond = AsyncMock(return_value={
                "response": "Go to Toronto General immediately.",
                "severity": "emergent",
                "reasoning": "Chest pain may indicate cardiac event.",
                "recommended_facility": fake_facility,
                "nearby_facilities": [],
                "turn_type": "triage",
            })
            MockAgent.return_value = mock_instance
            resp = client.post(
                "/chat/message",
                json={"session_id": FAKE_SESSION_ID, "content": "chest pain", "lat": 43.66, "lng": -79.38},
            )

        assert resp.status_code == 200
        mock_log.assert_called_once_with(43.66, -79.38, fake_facility)

    def test_shadow_call_not_dispatched_when_not_sampled(self, client):
        user_msg = self._fake_msg("user", "chest pain")
        assistant_msg = self._fake_msg("assistant", "Go to Toronto General immediately.")
        fake_facility = {
            "id": "fac-001", "name": "Toronto General Hospital",
            "category": "hospital", "address": "200 Elizabeth St",
            "lat": 43.659, "lng": -79.388, "distanceKm": 1.2,
        }

        with patch("routers.chat.add_message", side_effect=[user_msg, assistant_msg]), \
             patch("routers.chat.get_agent") as MockAgent, \
             patch("routers.chat.should_sample", return_value=False), \
             patch("routers.chat.log_routing_comparison") as mock_log:
            mock_instance = MagicMock()
            mock_instance.respond = AsyncMock(return_value={
                "response": "Go to Toronto General immediately.",
                "severity": "emergent",
                "reasoning": "Chest pain may indicate cardiac event.",
                "recommended_facility": fake_facility,
                "nearby_facilities": [],
                "turn_type": "triage",
            })
            MockAgent.return_value = mock_instance
            resp = client.post(
                "/chat/message",
                json={"session_id": FAKE_SESSION_ID, "content": "chest pain", "lat": 43.66, "lng": -79.38},
            )

        assert resp.status_code == 200
        mock_log.assert_not_called()

    def test_shadow_call_not_dispatched_on_followup_turn(self, client):
        user_msg = self._fake_msg("user", "hello")
        assistant_msg = self._fake_msg("assistant", "Can you tell me more?")

        with patch("routers.chat.add_message", side_effect=[user_msg, assistant_msg]), \
             patch("routers.chat.get_agent") as MockAgent, \
             patch("routers.chat.should_sample", return_value=True), \
             patch("routers.chat.log_routing_comparison") as mock_log:
            mock_instance = MagicMock()
            mock_instance.respond = AsyncMock(return_value={
                "response": "Can you tell me more?",
                "severity": None,
                "reasoning": None,
                "recommended_facility": None,
                "nearby_facilities": [],
                "turn_type": "followup",
            })
            MockAgent.return_value = mock_instance
            resp = client.post(
                "/chat/message",
                json={"session_id": FAKE_SESSION_ID, "content": "hello", "lat": 43.66, "lng": -79.38},
            )

        assert resp.status_code == 200
        mock_log.assert_not_called()


# ── Guest demo behaviour ──────────────────────────────────────────────────────

class _FakeGuest:
    id = FAKE_USER_ID_STR
    email = None
    is_guest = True


def _guest_client() -> TestClient:
    app = FastAPI()
    app.dependency_overrides[get_actor] = lambda: _FakeGuest()
    app.include_router(chat_router)
    return TestClient(app)


_TRIAGE_RESULT = {
    "response": "Go to Toronto General.", "severity": "urgent", "reasoning": "r",
    "recommended_facility": {"id": "f1", "name": "TGH", "category": "hospital", "address": "a",
                             "lat": 43.6, "lng": -79.3, "distanceKm": 1.0},
    "nearby_facilities": [], "turn_type": "triage",
}


def _msg(role: str) -> dict:
    return {"id": f"m-{role}", "session_id": FAKE_SESSION_ID, "user_id": FAKE_USER_ID_STR,
            "role": role, "content": "x", "created_at": "2026-10-07T00:00:00Z"}


class TestGuestChat:
    def test_rate_limited_guest_gets_busy_and_nothing_is_stored(self):
        with patch("routers.chat.check_rate_limit", return_value=120), \
             patch("routers.chat.add_message") as add:
            resp = _guest_client().post("/chat/message", json={"session_id": FAKE_SESSION_ID, "content": "hi"})
        assert resp.status_code == 429 and resp.json() == {"code": "busy", "retry_after": 120}
        add.assert_not_called()

    def test_llm_quota_error_maps_to_busy(self):
        class Quota(Exception):
            status_code = 429

        agent = MagicMock()
        agent.respond = AsyncMock(side_effect=Quota("rate limit"))
        with patch("routers.chat.check_rate_limit", return_value=None), \
             patch("routers.chat.add_message", return_value=_msg("user")), \
             patch("routers.chat.get_agent", return_value=agent):
            resp = _guest_client().post("/chat/message", json={"session_id": FAKE_SESSION_ID, "content": "hi"})
        assert resp.status_code == 429 and resp.json() == {"code": "busy", "retry_after": 60}

    def test_guest_skips_profile_lookup_and_records_recommendation(self):
        agent = MagicMock()
        agent.respond = AsyncMock(return_value=_TRIAGE_RESULT)
        with patch("routers.chat.check_rate_limit", return_value=None), \
             patch("routers.chat.add_message", side_effect=[_msg("user"), _msg("assistant")]), \
             patch("routers.chat.get_agent", return_value=agent), \
             patch("db.supabase_select") as profile_lookup, \
             patch("routers.chat.guest_store.record_event") as record, \
             patch("routers.chat.should_sample", return_value=False):
            resp = _guest_client().post("/chat/message", json={"session_id": FAKE_SESSION_ID, "content": "hi"})
        assert resp.status_code == 200
        profile_lookup.assert_not_called()
        assert agent.respond.call_args.kwargs["user_profile"] is None
        record.assert_called_once_with(FAKE_USER_ID_STR, "recommendation_shown", FAKE_SESSION_ID)

    def test_foreign_session_is_404(self):
        from services.guest_store import SessionNotFound
        with patch("routers.chat.check_rate_limit", return_value=None), \
             patch("routers.chat.add_message", side_effect=SessionNotFound("s")):
            resp = _guest_client().post("/chat/message", json={"session_id": FAKE_SESSION_ID, "content": "hi"})
        assert resp.status_code == 404

    def test_new_guest_session_records_session_started(self):
        session = {"id": FAKE_SESSION_ID, "user_id": FAKE_USER_ID_STR, "title": "hi",
                   "created_at": "2026-10-07T00:00:00Z", "updated_at": "2026-10-07T00:00:00Z"}
        with patch("routers.chat.create_session", return_value=session), \
             patch("routers.chat.guest_store.record_event") as record:
            resp = _guest_client().post("/chat/sessions", json={"first_message": "hi"})
        assert resp.status_code == 200
        record.assert_called_once_with(FAKE_USER_ID_STR, "session_started", FAKE_SESSION_ID)

    def test_event_failure_does_not_fail_the_request(self):
        session = {"id": FAKE_SESSION_ID, "user_id": FAKE_USER_ID_STR, "title": "hi",
                   "created_at": "2026-10-07T00:00:00Z", "updated_at": "2026-10-07T00:00:00Z"}
        with patch("routers.chat.create_session", return_value=session), \
             patch("routers.chat.guest_store.record_event", side_effect=RuntimeError("db")):
            assert _guest_client().post("/chat/sessions", json={"first_message": "hi"}).status_code == 200

    def test_signed_in_user_is_not_rate_limited(self):
        agent = MagicMock()
        agent.respond = AsyncMock(return_value={**_TRIAGE_RESULT, "turn_type": "followup", "recommended_facility": None})
        with patch("routers.chat.check_rate_limit") as limit, \
             patch("routers.chat.add_message", side_effect=[_msg("user"), _msg("assistant")]), \
             patch("routers.chat.get_agent", return_value=agent), \
             patch("db.supabase_select", return_value=None):
            resp = TestClient(_make_test_app()).post(
                "/chat/message", json={"session_id": FAKE_SESSION_ID, "content": "hi"})
        assert resp.status_code == 200
        limit.assert_not_called()

    def test_a_refused_turn_stores_nothing_and_does_not_count_against_the_rate_limit(self, monkeypatch, _turn_defaults):
        from services import admission

        monkeypatch.setenv("MAX_TURNS_IN_FLIGHT", "1")
        monkeypatch.setattr(admission, "_in_flight", 1)
        monkeypatch.setattr(admission, "retry_after_seconds", lambda: 4)
        with patch("routers.chat.check_rate_limit") as limit, \
             patch("routers.chat.add_message") as add:
            resp = _guest_client().post("/chat/message", json={"session_id": FAKE_SESSION_ID, "content": "hi"})

        assert resp.status_code == 429 and resp.json() == {"code": "busy", "retry_after": 4}
        assert resp.headers["retry-after"] == "4"
        limit.assert_not_called()
        add.assert_not_called()
        _turn_defaults.assert_not_called()

    def test_an_admitted_turn_frees_its_slot_when_it_ends(self, monkeypatch):
        from services import admission

        monkeypatch.setenv("MAX_TURNS_IN_FLIGHT", "1")
        monkeypatch.setattr(admission, "_in_flight", 0)
        with patch("routers.chat.check_rate_limit", return_value=None), \
             patch("routers.chat.add_message",
                   side_effect=[_msg("user"), _msg("assistant"), _msg("user"), _msg("assistant")]):
            client = _guest_client()
            first = client.post("/chat/message", json={"session_id": FAKE_SESSION_ID, "content": "hi"})
            second = client.post("/chat/message", json={"session_id": FAKE_SESSION_ID, "content": "again"})

        assert first.status_code == 200 and second.status_code == 200
        assert admission.in_flight() == 0


# ── Blocking work stays off the event loop ────────────────────────────────────

def _on_event_loop() -> bool:
    """True when called on the thread that runs the event loop (a worker thread has none)."""
    import asyncio

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return False
    return True


class TestChatDoesNotBlockTheEventLoop:
    """The agent awaits the LLM on the event loop, so no thread is held for an LLM call. The
    store calls hit the database and still run in the thread pool."""

    def test_the_agent_runs_on_the_event_loop_and_the_store_calls_in_the_thread_pool(self):
        seen: dict[str, bool] = {}

        async def respond(**_: object) -> dict:
            seen["respond"] = _on_event_loop()
            return _TRIAGE_RESULT

        def add_message(**kwargs: object) -> dict:
            seen[f"add_{kwargs['role']}"] = _on_event_loop()
            return _msg(str(kwargs["role"]))

        def recent(*_: object) -> list[dict]:
            seen["history"] = _on_event_loop()
            return []

        agent = MagicMock()
        agent.respond = respond
        with patch("routers.chat.check_rate_limit", return_value=None), \
             patch("routers.chat.get_recent_messages", side_effect=recent), \
             patch("routers.chat.add_message", side_effect=add_message), \
             patch("routers.chat.get_agent", return_value=agent), \
             patch("routers.chat.guest_store.record_event"), \
             patch("routers.chat.should_sample", return_value=False):
            resp = _guest_client().post("/chat/message", json={"session_id": FAKE_SESSION_ID, "content": "hi"})

        assert resp.status_code == 200
        assert seen == {"history": False, "add_user": False, "respond": True, "add_assistant": False}

    def test_session_creation_runs_in_the_thread_pool(self):
        seen: dict[str, bool] = {}
        session = {"id": FAKE_SESSION_ID, "user_id": FAKE_USER_ID_STR, "title": "hi",
                   "created_at": "2026-10-07T00:00:00Z", "updated_at": "2026-10-07T00:00:00Z"}

        def create_session(**_: object) -> dict:
            seen["create_session"] = _on_event_loop()
            return session

        with patch("routers.chat.create_session", side_effect=create_session), \
             patch("routers.chat.guest_store.record_event"):
            resp = _guest_client().post("/chat/sessions", json={"first_message": "hi"})

        assert resp.status_code == 200
        assert seen == {"create_session": False}

    def test_a_foreign_session_is_still_404_through_the_thread_pool(self):
        from services.guest_store import SessionNotFound

        with patch("routers.chat.check_rate_limit", return_value=None), \
             patch("routers.chat.add_message", side_effect=SessionNotFound("s")):
            resp = _guest_client().post("/chat/message", json={"session_id": FAKE_SESSION_ID, "content": "hi"})
        assert resp.status_code == 404


# ── History comes from the store ──────────────────────────────────────────────

class TestHistoryComesFromTheStore:
    def test_history_comes_from_the_store_and_reaches_the_agent(self, _turn_defaults):
        earlier = [{"role": "user", "content": "I have a fever"},
                   {"role": "assistant", "content": "Since when?"}]
        _turn_defaults.return_value = earlier
        agent = MagicMock()
        agent.respond = AsyncMock(return_value={**_TRIAGE_RESULT, "turn_type": "followup",
                                                "recommended_facility": None})
        with patch("routers.chat.check_rate_limit", return_value=None), \
             patch("routers.chat.add_message", side_effect=[_msg("user"), _msg("assistant")]), \
             patch("routers.chat.get_agent", return_value=agent):
            resp = _guest_client().post("/chat/message", json={"session_id": FAKE_SESSION_ID, "content": "hi"})

        assert resp.status_code == 200
        assert agent.respond.call_args.kwargs["history"] == earlier
        assert _turn_defaults.call_args.args == (FAKE_SESSION_ID, FAKE_USER_ID_STR, 20)

    def test_a_failed_history_read_is_503_and_nothing_reaches_the_llm(self, _turn_defaults):
        _turn_defaults.side_effect = RuntimeError("database down")
        agent = MagicMock()
        agent.respond = AsyncMock()
        with patch("routers.chat.check_rate_limit", return_value=None), \
             patch("routers.chat.add_message") as add, \
             patch("routers.chat.get_agent", return_value=agent):
            resp = _guest_client().post("/chat/message", json={"session_id": FAKE_SESSION_ID, "content": "hi"})

        assert resp.status_code == 503
        add.assert_not_called()
        agent.respond.assert_not_called()

    def test_the_session_list_is_read_from_the_store_on_every_request(self):
        with patch("routers.chat.get_past_conversations", return_value=([], {})) as read:
            client = TestClient(_make_test_app())
            assert client.get("/chat/sessions").status_code == 200
            assert client.get("/chat/sessions").status_code == 200
        assert read.call_count == 2
