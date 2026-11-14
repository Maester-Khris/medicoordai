import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi import FastAPI, HTTPException
from starlette.responses import PlainTextResponse
from starlette.testclient import TestClient

from middleware.auth import AuthMiddleware


def _make_client():
    app = FastAPI()
    app.add_middleware(AuthMiddleware)

    @app.get("/probe")
    async def probe():
        return PlainTextResponse("ok")

    @app.get("/metrics")
    async def metrics():
        return PlainTextResponse("ok")

    return TestClient(app, raise_server_exceptions=False)


class TestAuthMiddleware:
    @pytest.fixture(autouse=True)
    def _non_demo(self, monkeypatch):
        monkeypatch.setenv("DEMO_MODE", "false")  # these cases cover the Supabase-user path

    def test_propagates_503_when_auth_service_down(self):
        with patch(
            "middleware.auth.verify_token",
            side_effect=HTTPException(503, "Auth service unavailable"),
        ):
            with _make_client() as client:
                resp = client.get("/probe", headers={"Authorization": "Bearer tok"})
        assert resp.status_code == 503

    def test_swallows_401_and_treats_as_anonymous(self):
        with patch(
            "middleware.auth.verify_token",
            side_effect=HTTPException(401, "invalid token"),
        ):
            with _make_client() as client:
                resp = client.get("/probe", headers={"Authorization": "Bearer tok"})
        assert resp.status_code == 200

    def test_metrics_path_bypasses_supabase_verification_entirely(self):
        with patch(
            "middleware.auth.verify_token",
            side_effect=HTTPException(503, "Auth service unavailable"),
        ) as mock_verify:
            with _make_client() as client:
                resp = client.get("/metrics", headers={"Authorization": "Bearer some-static-secret"})
        assert resp.status_code == 200
        mock_verify.assert_not_called()


class TestDemoModeSkipsTokenVerification:
    def test_demo_mode_never_calls_supabase_for_a_bearer_header(self, monkeypatch):
        monkeypatch.setenv("DEMO_MODE", "true")
        with patch("middleware.auth.verify_token", side_effect=AssertionError("must not be called")) as mock_verify:
            with _make_client() as client:
                resp = client.get("/probe", headers={"Authorization": "Bearer junk"})
        assert resp.status_code == 200
        mock_verify.assert_not_called()
