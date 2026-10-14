"""
GET /internal/memory-profile: the staging-only tracemalloc growth report. Off unless
MEMORY_PROFILE is set, and then only for callers that send the internal token.
"""
import os
import sys
import tracemalloc
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi.testclient import TestClient

import main
from services import memory_profile

client = TestClient(main.app)
TOKEN = "t" * 32


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DEMO_INTERNAL_TOKEN", TOKEN)
    monkeypatch.delenv("MEMORY_PROFILE", raising=False)
    yield
    if tracemalloc.is_tracing():
        tracemalloc.stop()
    memory_profile._baseline = None


def test_route_is_404_when_the_switch_is_off():
    resp = client.get("/internal/memory-profile", headers={"X-Internal": TOKEN})
    assert resp.status_code == 404


def test_route_rejects_a_caller_without_the_internal_token(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MEMORY_PROFILE", "1")
    assert client.get("/internal/memory-profile").status_code == 403
    assert client.get("/internal/memory-profile", headers={"X-Internal": "wrong"}).status_code == 403


def test_route_is_closed_when_no_internal_token_is_configured(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MEMORY_PROFILE", "1")
    monkeypatch.setenv("DEMO_INTERNAL_TOKEN", "")
    assert client.get("/internal/memory-profile", headers={"X-Internal": ""}).status_code == 403


def test_start_does_nothing_when_the_switch_is_off():
    memory_profile.start()
    assert not tracemalloc.is_tracing()


def test_growth_names_the_site_that_allocated_after_the_baseline(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MEMORY_PROFILE", "1")
    memory_profile.start()
    held = [bytearray(1024) for _ in range(2000)]  # about 2 MB, allocated on this line
    resp = client.get("/internal/memory-profile", headers={"X-Internal": TOKEN})
    assert resp.status_code == 200
    body = resp.json()
    assert body["top"], "expected at least one growing site"
    assert body["top"][0]["site"].startswith("tests/test_memory_profile.py") or "test_memory_profile.py" in body["top"][0]["site"]
    assert body["top"][0]["size_diff_bytes"] >= 2_000_000
    assert body["traced_bytes"] >= 2_000_000
    assert len(held) == 2000


def test_growth_is_limited_and_sorted_largest_first(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MEMORY_PROFILE", "1")
    memory_profile.start()
    held = [bytearray(100) for _ in range(500)]
    top = memory_profile.growth(limit=1)["top"]
    assert len(top) == 1
    assert len(held) == 500
