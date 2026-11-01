import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import patch

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

import middleware.auth as auth

GUEST = "3f2b1c9e-8a47-4d1e-9c55-0a1b2c3d4e5f"


def _client() -> TestClient:
    app = FastAPI()

    @app.get("/who")
    async def who(actor: object = Depends(auth.get_actor)) -> dict:
        return {"id": str(actor.id), "is_guest": actor.is_guest}  # type: ignore[attr-defined]

    return TestClient(app)


@pytest.fixture()
def demo(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.setenv("DEMO_INTERNAL_TOKEN", "s3cret")
    with patch.object(auth.guest_store, "touch_guest", return_value=False) as touch, \
         patch.object(auth, "purge_if_due") as purge:
        yield touch, purge


def test_guest_header_becomes_actor(demo) -> None:
    touch, _ = demo
    resp = _client().get("/who", headers={"X-Guest-Id": GUEST})
    assert resp.status_code == 200 and resp.json() == {"id": GUEST, "is_guest": True}
    touch.assert_called_once_with(GUEST, False)


@pytest.mark.parametrize("bad", ["", "abc", "1; drop table guests", "null"])
def test_guest_header_malformed_is_400(demo, bad: str) -> None:
    touch, _ = demo
    headers = {"X-Guest-Id": bad} if bad else {}
    assert _client().get("/who", headers=headers).status_code == 400
    touch.assert_not_called()


def test_guest_id_is_normalised_to_canonical_form(demo) -> None:
    resp = _client().get("/who", headers={"X-Guest-Id": GUEST.upper()})
    assert resp.json()["id"] == GUEST


def test_internal_token_marks_guest_internal(demo) -> None:
    touch, _ = demo
    _client().get("/who", headers={"X-Guest-Id": GUEST, "X-Internal": "s3cret"})
    touch.assert_called_once_with(GUEST, True)


def test_wrong_or_unset_internal_token_does_not_mark(demo, monkeypatch: pytest.MonkeyPatch) -> None:
    touch, _ = demo
    _client().get("/who", headers={"X-Guest-Id": GUEST, "X-Internal": "nope"})
    touch.assert_called_once_with(GUEST, False)
    touch.reset_mock()
    monkeypatch.setenv("DEMO_INTERNAL_TOKEN", "")
    _client().get("/who", headers={"X-Guest-Id": GUEST, "X-Internal": ""})
    touch.assert_called_once_with(GUEST, False)


def test_new_guest_triggers_purge_check(demo) -> None:
    touch, purge = demo
    touch.return_value = True
    _client().get("/who", headers={"X-Guest-Id": GUEST})
    purge.assert_called_once_with()


def test_database_failure_is_503(demo) -> None:
    touch, _ = demo
    touch.side_effect = RuntimeError("pool timeout")
    assert _client().get("/who", headers={"X-Guest-Id": GUEST}).status_code == 503


def test_flag_off_requires_bearer_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEMO_MODE", raising=False)
    assert _client().get("/who", headers={"X-Guest-Id": GUEST}).status_code == 401


def test_flag_off_uses_supabase_user(monkeypatch: pytest.MonkeyPatch) -> None:
    import types
    monkeypatch.delenv("DEMO_MODE", raising=False)
    user = types.SimpleNamespace(id="u-1", email="a@b.c")
    with patch.object(auth, "verify_token", return_value=user):
        resp = _client().get("/who", headers={"Authorization": "Bearer t"})
    assert resp.json() == {"id": "u-1", "is_guest": False}


def test_cors_allows_guest_headers() -> None:
    import main
    resp = TestClient(main.app).options(
        "/chat/sessions",
        headers={
            "Origin": main.ALLOWED_ORIGINS[0],
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "x-guest-id,x-internal",
        },
    )
    allowed = resp.headers.get("access-control-allow-headers", "").lower()
    assert resp.status_code == 200 and "x-guest-id" in allowed and "x-internal" in allowed


def test_non_ascii_internal_header_is_not_a_500(demo) -> None:
    touch, _ = demo
    resp = _client().get("/who", headers={"X-Guest-Id": GUEST, "X-Internal": "s\xe9cret".encode("latin-1")})
    assert resp.status_code == 200
    touch.assert_called_once_with(GUEST, False)
