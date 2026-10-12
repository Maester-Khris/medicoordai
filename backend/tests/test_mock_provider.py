"""
The mock of the two external providers used in load tests (scripts/load/mock_provider.py).
It must be shaped like the real ones: the real Groq SDK parses its chat completions and the
real services.routing.parse_route reads its routes.
"""
import json
import os
import statistics
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi.testclient import TestClient

from scripts.load import mock_provider
from services.routing import parse_route

SEVERITIES = {"routine", "moderate", "urgent", "emergent"}
TOOLS = [{"type": "function", "function": {"name": "triage_response", "parameters": {}}}]


@pytest.fixture(autouse=True)
def _no_delay(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MOCK_DELAY_SCALE", "0")
    mock_provider.reset_stats()


client = TestClient(mock_provider.app)


def _chat(messages: list[dict], tools: list[dict] | None = None) -> dict:
    body: dict = {"model": "openai/gpt-oss-120b", "messages": messages}
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"
    resp = client.post("/openai/v1/chat/completions", json=body)
    assert resp.status_code == 200
    return resp.json()


def test_a_request_with_tools_gets_a_triage_tool_call():
    data = _chat([{"role": "user", "content": "chest pain"}], TOOLS)
    choice = data["choices"][0]
    assert choice["finish_reason"] == "tool_calls"
    call = choice["message"]["tool_calls"][0]
    assert call["function"]["name"] == "triage_response"
    args = json.loads(call["function"]["arguments"])
    assert args["severity"] in SEVERITIES
    assert args["information_sufficient"] is True
    assert isinstance(args["reasoning"], str)


def test_a_request_without_tools_gets_text_that_names_the_facility_it_was_given():
    grounding = (
        "Symptom severity has been classified as: urgent.\n"
        "The nearest appropriate facility is: Mock General Hospital at 1 Main St, approximately 2.4 km away."
    )
    data = _chat([{"role": "user", "content": "chest pain"}, {"role": "system", "content": grounding}])
    choice = data["choices"][0]
    assert choice["finish_reason"] == "stop"
    assert "Mock General Hospital" in choice["message"]["content"]
    assert not choice["message"].get("tool_calls")


def test_the_reply_reports_token_usage_like_a_real_turn():
    usage = _chat([{"role": "user", "content": "x"}], TOOLS)["usage"]
    assert usage["prompt_tokens"] > 0 and usage["completion_tokens"] > 0
    assert usage["total_tokens"] == usage["prompt_tokens"] + usage["completion_tokens"]


def test_a_route_is_parsed_by_the_real_route_parser():
    resp = client.get("/v1/routing", params={"waypoints": "43.70,-79.40|43.66,-79.38", "mode": "drive", "apiKey": "k"})
    assert resp.status_code == 200
    route = parse_route(resp.json())
    assert route is not None
    assert route["eta_minutes"] > 0 and route["distance_km"] > 0
    assert len(route["geometry"]) >= 100
    assert route["geometry"][0] == [43.70, -79.40]


def test_walking_takes_longer_than_driving_over_the_same_distance():
    def eta(mode: str) -> int:
        params = {"waypoints": "43.70,-79.40|43.60,-79.30", "mode": mode, "apiKey": "k"}
        return parse_route(client.get("/v1/routing", params=params).json())["eta_minutes"]

    assert eta("walk") > eta("bicycle") > eta("drive")


def test_a_route_request_without_waypoints_is_a_400():
    assert client.get("/v1/routing", params={"mode": "drive"}).status_code == 400


def test_stats_count_calls_and_the_longest_conversation_seen():
    _chat([{"role": "user", "content": "a"}], TOOLS)
    _chat([{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}, {"role": "user", "content": "c"}], TOOLS)
    client.get("/v1/routing", params={"waypoints": "43.70,-79.40|43.66,-79.38", "mode": "walk"})
    stats = client.get("/stats").json()
    assert stats["llm_calls"] == 2
    assert stats["routing_calls"] == 1
    assert stats["max_user_turns_seen"] == 2
    assert client.post("/stats/reset").json()["llm_calls"] == 0
    assert client.get("/stats").json()["routing_calls"] == 0


def test_llm_delays_follow_the_configured_mean(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MOCK_DELAY_SCALE", "1")
    samples = [mock_provider.llm_delay_seconds() for _ in range(4000)]
    assert statistics.mean(samples) == pytest.approx(2.2, rel=0.1)


def test_route_delays_follow_the_configured_percentiles(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MOCK_DELAY_SCALE", "1")
    samples = sorted(mock_provider.route_delay_seconds() for _ in range(4000))
    assert samples[len(samples) // 2] == pytest.approx(1.0, rel=0.1)
    assert samples[int(len(samples) * 0.95)] == pytest.approx(1.9, rel=0.15)
