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

from fastapi.testclient import TestClient

import main

client = TestClient(main.app)


def test_health_omits_neo4j_when_provider_not_neo4j():
    with patch.dict(os.environ, {"GRAPH_RAG_PROVIDER": "off"}):
        resp = client.get("/health")
    assert resp.status_code == 200
    assert "neo4j" not in resp.json()


def test_health_reports_neo4j_ok_when_ping_succeeds():
    fake_provider = MagicMock()
    fake_provider.ping.return_value = None
    with patch.dict(os.environ, {"GRAPH_RAG_PROVIDER": "neo4j"}), \
         patch("main.get_graph_provider", return_value=fake_provider):
        resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["neo4j"] == "ok"


def test_health_reports_neo4j_unreachable_when_ping_fails():
    fake_provider = MagicMock()
    fake_provider.ping.side_effect = ConnectionError("down")
    with patch.dict(os.environ, {"GRAPH_RAG_PROVIDER": "neo4j"}), \
         patch("main.get_graph_provider", return_value=fake_provider):
        resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["neo4j"] == "unreachable"

def test_health_reports_demo_db_unreachable(monkeypatch):
    import main
    monkeypatch.setenv("DEMO_MODE", "true")

    def boom(*_args, **_kwargs):
        raise RuntimeError("down")

    monkeypatch.setattr(main.demo_db, "fetch_one", boom)
    body = main.health()
    assert body["demoMode"] is True and body["demoDb"] == "unreachable"


def test_health_omits_demo_db_when_flag_off(monkeypatch):
    import main
    monkeypatch.delenv("DEMO_MODE", raising=False)
    body = main.health()
    assert body["demoMode"] is False and "demoDb" not in body
