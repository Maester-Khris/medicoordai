import os
import sys
import threading

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

import observability


def _client() -> TestClient:
    app = FastAPI()

    @app.get("/metrics")
    def metrics(_: None = Depends(observability.verify_metrics_token)) -> dict:
        return {"ok": True}

    return TestClient(app)


def test_metrics_is_closed_when_no_token_is_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("METRICS_BEARER_TOKEN", raising=False)
    assert _client().get("/metrics").status_code == 503
    assert _client().get("/metrics", headers={"Authorization": "Bearer anything"}).status_code == 503


def test_a_blank_token_counts_as_not_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("METRICS_BEARER_TOKEN", "   ")
    assert _client().get("/metrics", headers={"Authorization": "Bearer    "}).status_code == 503


def test_metrics_rejects_a_missing_or_wrong_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("METRICS_BEARER_TOKEN", "s3cret")
    assert _client().get("/metrics").status_code == 403
    assert _client().get("/metrics", headers={"Authorization": "Bearer nope"}).status_code == 403
    assert _client().get("/metrics", headers={"Authorization": "s3cret"}).status_code == 403


def test_metrics_accepts_the_configured_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("METRICS_BEARER_TOKEN", "s3cret")
    assert _client().get("/metrics", headers={"Authorization": "Bearer s3cret"}).status_code == 200


def test_init_metrics_starts_no_background_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    # The Grafana variables used to start a push thread; they must have no effect any more.
    monkeypatch.setenv("GRAFANA_PROMETHEUS_REMOTE_WRITE_URL", "https://example.invalid/push")
    monkeypatch.setenv("GRAFANA_PROMETHEUS_INSTANCE_ID", "1")
    monkeypatch.setenv("GRAFANA_API_TOKEN", "t")
    before = threading.active_count()
    observability.init_metrics(FastAPI())
    assert threading.active_count() == before
    assert not hasattr(observability, "push_to_gateway")
