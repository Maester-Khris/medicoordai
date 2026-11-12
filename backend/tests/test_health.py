"""
Tests for GET /health, specifically its Neo4j keep-alive ping — added to
stop AuraDB's free-tier 72h auto-pause from expiring between real requests
(graph/snomed_neo4j/provider.py). Imports main.app directly but never enters
its lifespan context manager, so no Supabase warm-up call is triggered.
"""
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

import main

client = TestClient(main.app)
INTERNAL = {"X-Internal": "health-test-token"}


@pytest.fixture(autouse=True)
def _internal_token(monkeypatch):
    monkeypatch.setenv("DEMO_INTERNAL_TOKEN", "health-test-token")


def test_health_omits_neo4j_when_provider_not_neo4j():
    with patch.dict(os.environ, {"GRAPH_RAG_PROVIDER": "off"}):
        resp = client.get("/health", headers=INTERNAL)
    assert resp.status_code == 200
    assert "neo4j" not in resp.json()


def test_health_reports_neo4j_ok_when_ping_succeeds():
    fake_provider = MagicMock()
    fake_provider.ping.return_value = None
    with patch.dict(os.environ, {"GRAPH_RAG_PROVIDER": "neo4j"}), \
         patch("main.get_graph_provider", return_value=fake_provider):
        resp = client.get("/health", headers=INTERNAL)
    assert resp.status_code == 200
    assert resp.json()["neo4j"] == "ok"


def test_health_reports_neo4j_unreachable_when_ping_fails():
    fake_provider = MagicMock()
    fake_provider.ping.side_effect = ConnectionError("down")
    with patch.dict(os.environ, {"GRAPH_RAG_PROVIDER": "neo4j"}), \
         patch("main.get_graph_provider", return_value=fake_provider):
        resp = client.get("/health", headers=INTERNAL)
    assert resp.status_code == 200
    assert resp.json()["neo4j"] == "unreachable"

def test_health_reports_demo_db_unreachable(monkeypatch):
    import main
    monkeypatch.setenv("DEMO_MODE", "true")

    def boom(*_args, **_kwargs):
        raise RuntimeError("down")

    monkeypatch.setattr(main.demo_db, "fetch_one", boom)
    body = main.health_detail()
    assert body["demoMode"] is True and body["demoDb"] == "unreachable"


def test_health_omits_demo_db_when_flag_off(monkeypatch):
    import main
    monkeypatch.delenv("DEMO_MODE", raising=False)
    body = main.health_detail()
    assert body["demoMode"] is False and "demoDb" not in body


def test_health_says_when_a_provider_is_stubbed(monkeypatch):
    monkeypatch.delenv("DEMO_MODE", raising=False)
    monkeypatch.delenv("GROQ_BASE_URL", raising=False)
    monkeypatch.delenv("GEOAPIFY_BASE_URL", raising=False)
    assert "stubbed" not in client.get("/health", headers=INTERNAL).json()
    monkeypatch.setenv("GEOAPIFY_BASE_URL", "http://mock:9000")
    assert client.get("/health", headers=INTERNAL).json()["stubbed"] is True


def test_health_pings_neo4j_for_the_semantic_provider_value():
    fake_provider = MagicMock()
    fake_provider.semantic_status.return_value = {"state": "ready", "model": "biolord", "rows": 3}
    with patch.dict(os.environ, {"GRAPH_RAG_PROVIDER": "neo4j_semantic"}), \
         patch("main.get_graph_provider", return_value=fake_provider):
        body = client.get("/health", headers=INTERNAL).json()
    fake_provider.ping.assert_called_once()
    fake_provider.maybe_reload.assert_called_once()  # a health poll is what notices a freshly built index
    assert body["neo4j"] == "ok" and body["semantic"] == {"state": "ready", "model": "biolord", "rows": 3}


def test_health_reports_semantic_state_and_never_fails_when_status_raises():
    fake_provider = MagicMock()
    fake_provider.semantic_status.side_effect = RuntimeError("boom")
    with patch.dict(os.environ, {"GRAPH_RAG_PROVIDER": "neo4j_semantic"}), \
         patch("main.get_graph_provider", return_value=fake_provider):
        resp = client.get("/health", headers=INTERNAL)
    assert resp.status_code == 200 and resp.json()["semantic"] == {"state": "error"}


def test_health_omits_semantic_for_the_plain_neo4j_provider():
    fake_provider = MagicMock()
    with patch.dict(os.environ, {"GRAPH_RAG_PROVIDER": "neo4j"}), \
         patch("main.get_graph_provider", return_value=fake_provider):
        body = client.get("/health", headers=INTERNAL).json()
    assert "semantic" not in body and body["neo4j"] == "ok"


def test_health_shows_only_the_status_to_an_unauthenticated_caller(monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.setenv("GEOAPIFY_BASE_URL", "http://mock:9000")
    assert client.get("/health").json() == {"status": "ok"}
    assert client.get("/health", headers={"X-Internal": "wrong"}).json() == {"status": "ok"}
    assert set(client.get("/health", headers=INTERNAL).json()) >= {"status", "llmProvider", "demoMode", "stubbed"}


def test_the_trimmed_health_still_runs_every_check(monkeypatch):
    """The neo4j ping doubles as the Aura keep-alive: it must run even when the body is trimmed."""
    monkeypatch.setenv("GRAPH_RAG_PROVIDER", "neo4j")
    fake_provider = MagicMock()
    with patch("main.get_graph_provider", return_value=fake_provider):
        assert client.get("/health").json() == {"status": "ok"}
    fake_provider.ping.assert_called_once()


def test_the_api_docs_are_off_by_default():
    assert client.get("/openapi.json").status_code == 404
    assert client.get("/docs").status_code == 404
    assert client.get("/redoc").status_code == 404


def test_the_docs_flag():
    assert main.docs_enabled({"ENABLE_DOCS": "1"}) and main.docs_enabled({"ENABLE_DOCS": "true"})
    assert not main.docs_enabled({}) and not main.docs_enabled({"ENABLE_DOCS": "0"})
