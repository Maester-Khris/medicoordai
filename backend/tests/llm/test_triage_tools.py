"""
Unit tests for proximity service, agent message building, and follow-up ceiling.
No real LLM calls — all LLM interactions are mocked.
No environment variables or network access required.
"""
import json
import asyncio
import os
import sys

# Add backend/ to sys.path so bare imports (services.*, llm.*, cache) resolve
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

MOCK_FACILITIES = [
    {
        "id": "fac-001", "name": "Toronto General Hospital",
        "category": "hospital", "address": "200 Elizabeth St, Toronto",
        "lat": 43.659, "lng": -79.388,
        "accepted_severity": ["emergent", "urgent", "moderate", "routine"],
    },
    {
        "id": "fac-002", "name": "Bay Centre Walk-In Clinic",
        "category": "ambulatory", "address": "444 Yonge St, Toronto",
        "lat": 43.661, "lng": -79.383,
        "accepted_severity": ["urgent", "moderate", "routine"],
    },
    {
        "id": "fac-003", "name": "Rosedale Residential Care",
        "category": "residential", "address": "120 Bloor St E, Toronto",
        "lat": 43.668, "lng": -79.380,
        "accepted_severity": ["routine"],
    },
    {
        "id": "fac-004", "name": "St. Michael's Hospital",
        "category": "hospital", "address": "30 Bond St, Toronto",
        "lat": 43.653, "lng": -79.376,
        "accepted_severity": ["emergent", "urgent", "moderate", "routine"],
    },
]


@pytest.fixture(autouse=True)
def mock_facilities_cache():
    with patch("services.proximity.get_cached_facilities") as m:
        m.return_value = (MOCK_FACILITIES, '"mock-etag"')
        yield m


# -----------------------------------------------------------------------
# Haversine
# -----------------------------------------------------------------------

class TestHaversine:
    def test_same_point_is_zero(self):
        from services.proximity import haversine_km
        assert haversine_km(43.659, -79.388, 43.659, -79.388) == 0.0

    def test_known_approximate_distance(self):
        from services.proximity import haversine_km
        # Toronto General to CN Tower approx 1.9 km
        dist = haversine_km(43.659, -79.388, 43.642, -79.387)
        assert 1.0 < dist < 3.0

    def test_symmetry(self):
        from services.proximity import haversine_km
        d1 = haversine_km(43.659, -79.388, 43.668, -79.380)
        d2 = haversine_km(43.668, -79.380, 43.659, -79.388)
        assert abs(d1 - d2) < 0.001


# -----------------------------------------------------------------------
# find_nearest_facilities
# -----------------------------------------------------------------------

class TestFindNearestFacilities:
    def test_returns_list_not_single(self):
        from services.proximity import find_nearest_facilities
        result = find_nearest_facilities(43.660, -79.385, "routine", top_n=3)
        assert isinstance(result, list)

    def test_top_n_respected(self):
        from services.proximity import find_nearest_facilities
        result = find_nearest_facilities(43.660, -79.385, "routine", top_n=2)
        assert result is not None
        assert len(result) <= 2

    def test_sorted_by_distance_ascending(self):
        from services.proximity import find_nearest_facilities
        result = find_nearest_facilities(43.660, -79.385, "routine", top_n=3)
        assert result is not None
        distances = [f["distanceKm"] for f in result]
        assert distances == sorted(distances)

    def test_emergent_only_returns_hospitals(self):
        from services.proximity import find_nearest_facilities
        result = find_nearest_facilities(43.660, -79.385, "emergent", top_n=3)
        assert result is not None
        for f in result:
            assert f["category"] == "hospital"

    def test_all_results_accept_severity(self):
        from services.proximity import find_nearest_facilities
        for severity in ["routine", "moderate", "urgent", "emergent"]:
            result = find_nearest_facilities(43.660, -79.385, severity, top_n=5)
            assert result is not None
            for f in result:
                assert severity in f["accepted_severity"]

    def test_returns_none_when_cache_empty(self):
        from services.proximity import find_nearest_facilities
        with patch("services.proximity.get_cached_facilities") as m:
            m.return_value = (None, None)
            result = find_nearest_facilities(43.660, -79.385, "urgent")
            assert result is None

    def test_returns_empty_list_when_no_eligible(self):
        from services.proximity import find_nearest_facilities
        with patch("services.proximity.get_cached_facilities") as m:
            m.return_value = ([], '"etag"')
            result = find_nearest_facilities(43.660, -79.385, "emergent")
            assert result == []

    def test_distance_field_present_and_positive(self):
        from services.proximity import find_nearest_facilities
        result = find_nearest_facilities(43.660, -79.385, "urgent", top_n=2)
        assert result is not None
        for f in result:
            assert "distanceKm" in f
            assert f["distanceKm"] > 0

    def test_result_fields_complete(self):
        from services.proximity import find_nearest_facilities
        result = find_nearest_facilities(43.660, -79.385, "moderate", top_n=1)
        assert result is not None and len(result) > 0
        required = ["id", "name", "category", "address", "lat", "lng", "distanceKm"]
        for field in required:
            assert field in result[0]

    def test_first_item_is_nearest(self):
        from services.proximity import find_nearest_facilities
        result = find_nearest_facilities(43.660, -79.385, "routine", top_n=3)
        assert result is not None and len(result) > 1
        assert result[0]["distanceKm"] <= result[1]["distanceKm"]


# -----------------------------------------------------------------------
# LLMAgent — message building
# -----------------------------------------------------------------------

def make_agent():
    from services.llm_agent import LLMAgent
    return LLMAgent(client=MagicMock())


class TestAgentMessageBuilding:
    def test_system_prompt_is_first(self):
        agent = make_agent()
        msgs = agent._build_messages("I have a headache", [])
        assert msgs[0].role == "system"
        assert "MediCoord" in msgs[0].content

    def test_user_message_is_last(self):
        agent = make_agent()
        msgs = agent._build_messages("I have a headache", [])
        assert msgs[-1].role == "user"
        assert msgs[-1].content == "I have a headache"

    def test_history_trimmed_to_context_window(self):
        os.environ["TRIAGE_CONTEXT_WINDOW"] = "4"
        agent = make_agent()
        history = [
            {"role": "user" if i % 2 == 0 else "assistant", "content": f"msg {i}"}
            for i in range(20)
        ]
        msgs = agent._build_messages("new message", history)
        # system + 4 history + 1 user = 6
        assert len(msgs) == 6

    def test_empty_history_two_messages(self):
        agent = make_agent()
        msgs = agent._build_messages("I feel dizzy", [])
        assert len(msgs) == 2  # system + user


# -----------------------------------------------------------------------
# LLMAgent — follow-up ceiling
# -----------------------------------------------------------------------

class TestFollowupCeiling:
    def test_force_classify_at_ceiling(self):
        from services.llm_agent import LLMAgent
        from llm.tools import TRIAGE_RESPONSE

        mock_client = MagicMock()
        mock_client.chat = AsyncMock(return_value=MagicMock(
            finish_reason="tool_calls",
            content=None,
            tool_calls=[{
                "id": "tc1",
                "name": TRIAGE_RESPONSE.name,
                "arguments": json.dumps({
                    "severity": "moderate",
                    "reasoning": "Persistent symptoms",
                }),
            }],
        ))
        os.environ["TRIAGE_MAX_FOLLOWUPS"] = "2"
        agent = LLMAgent(client=mock_client)

        history = [
            {"role": "user", "content": "I have a fever"},
            {"role": "assistant", "content": "How long have you had it?"},
            {"role": "user", "content": "Since yesterday"},
            {"role": "assistant", "content": "Any other symptoms?"},
        ]
        result = asyncio.run(agent.respond("Just tired", history))

        call_kwargs = mock_client.chat.call_args_list[0].kwargs
        assert call_kwargs.get("force_tool") == TRIAGE_RESPONSE.name
        assert result["turn_type"] == "triage"
        assert result["severity"] == "moderate"

    def test_followup_turn_no_force_tool(self):
        from services.llm_agent import LLMAgent

        mock_client = MagicMock()
        mock_client.chat = AsyncMock(return_value=MagicMock(
            finish_reason="stop",
            content="How long have you had these symptoms?",
            tool_calls=None,
        ))
        os.environ["TRIAGE_MAX_FOLLOWUPS"] = "4"
        agent = LLMAgent(client=mock_client)

        result = asyncio.run(agent.respond("I have a headache", []))

        call_kwargs = mock_client.chat.call_args_list[0].kwargs
        assert call_kwargs.get("force_tool") is None
        assert result["turn_type"] == "followup"
        assert result["severity"] is None


# -----------------------------------------------------------------------
# LLMAgent — triage result shape
# -----------------------------------------------------------------------

class TestTriageResultShape:
    def test_triage_result_contains_nearby_facilities(self):
        from services.llm_agent import LLMAgent
        from llm.tools import TRIAGE_RESPONSE

        mock_client = MagicMock()
        mock_client.chat = AsyncMock(side_effect=[
            MagicMock(
                finish_reason="tool_calls",
                content=None,
                tool_calls=[{
                    "id": "tc1",
                    "name": TRIAGE_RESPONSE.name,
                    "arguments": json.dumps({
                        "severity": "urgent",
                        "reasoning": "High fever with pain",
                    }),
                }],
            ),
            MagicMock(
                finish_reason="stop",
                content="Please go to Bay Centre Walk-In.",
                tool_calls=None,
            ),
        ])

        # Three prior user turns so user_turns >= TRIAGE_MIN_TURNS (default 3)
        history = [
            {"role": "user",      "content": "I feel unwell"},
            {"role": "assistant", "content": "Can you describe your symptoms?"},
            {"role": "user",      "content": "I have a headache and fever"},
            {"role": "assistant", "content": "How long have you had these symptoms?"},
            {"role": "user",      "content": "Since this morning"},
            {"role": "assistant", "content": "Any chills or nausea alongside the fever?"},
        ]
        agent = LLMAgent(client=mock_client)
        result = asyncio.run(agent.respond("I have a high fever", history, lat=43.660, lng=-79.385))

        assert result["turn_type"] == "triage"
        assert result["severity"] == "urgent"
        assert result["recommended_facility"] is not None
        assert isinstance(result["nearby_facilities"], list)
        recommended_id = result["recommended_facility"]["id"]
        nearby_ids = [f["id"] for f in result["nearby_facilities"]]
        assert recommended_id not in nearby_ids

    def test_no_location_returns_no_facility(self):
        from services.llm_agent import LLMAgent
        from llm.tools import TRIAGE_RESPONSE

        mock_client = MagicMock()
        mock_client.chat = AsyncMock(side_effect=[
            MagicMock(
                finish_reason="tool_calls",
                content=None,
                tool_calls=[{
                    "id": "tc1",
                    "name": TRIAGE_RESPONSE.name,
                    "arguments": json.dumps({
                        "severity": "routine",
                        "reasoning": "Minor cold",
                    }),
                }],
            ),
            MagicMock(
                finish_reason="stop",
                content="See a walk-in when convenient.",
                tool_calls=None,
            ),
        ])

        agent = LLMAgent(client=mock_client)
        result = asyncio.run(agent.respond("I have a cold", [], lat=None, lng=None))

        assert result["recommended_facility"] is None
        assert result["nearby_facilities"] == []


# -----------------------------------------------------------------------
# LLMAgent — grounding check logging (Sprint 17 instrumentation)
# -----------------------------------------------------------------------

class TestTriageGroundingLogged:
    def test_grounding_checked_and_logged_when_facility_present(self, caplog):
        from services.llm_agent import LLMAgent
        from llm.tools import TRIAGE_RESPONSE

        mock_client = MagicMock()
        mock_client.chat = AsyncMock(side_effect=[
            MagicMock(
                finish_reason="tool_calls",
                content=None,
                tool_calls=[{
                    "id": "tc1",
                    "name": TRIAGE_RESPONSE.name,
                    "arguments": json.dumps({
                        "severity": "urgent",
                        "reasoning": "High fever with pain",
                    }),
                }],
            ),
            MagicMock(
                finish_reason="stop",
                content="Please go to Bay Centre Walk-In Clinic.",
                tool_calls=None,
            ),
        ])

        history = [
            {"role": "user",      "content": "I feel unwell"},
            {"role": "assistant", "content": "Can you describe your symptoms?"},
            {"role": "user",      "content": "I have a headache and fever"},
            {"role": "assistant", "content": "How long have you had these symptoms?"},
            {"role": "user",      "content": "Since this morning"},
            {"role": "assistant", "content": "Any chills or nausea alongside the fever?"},
        ]
        agent = LLMAgent(client=mock_client)

        with caplog.at_level("INFO"):
            result = asyncio.run(agent.respond("I have a high fever", history, lat=43.660, lng=-79.385))

        assert result["turn_type"] == "triage"
        grounding_records = [r for r in caplog.records if r.msg == "triage_grounding_checked"]
        assert len(grounding_records) == 1
        record = grounding_records[0]
        assert record.facility_provided is True
        assert record.user_turns == 3

    def test_grounding_logged_as_none_when_no_facility(self, caplog):
        from services.llm_agent import LLMAgent
        from llm.tools import TRIAGE_RESPONSE

        mock_client = MagicMock()
        mock_client.chat = AsyncMock(side_effect=[
            MagicMock(
                finish_reason="tool_calls",
                content=None,
                tool_calls=[{
                    "id": "tc1",
                    "name": TRIAGE_RESPONSE.name,
                    "arguments": json.dumps({
                        "severity": "routine",
                        "reasoning": "Minor cold",
                    }),
                }],
            ),
            MagicMock(
                finish_reason="stop",
                content="See a walk-in when convenient.",
                tool_calls=None,
            ),
        ])

        # Empty history → 0 user turns; set TRIAGE_MIN_TURNS=0 so triage fires
        # without the minimum-turn gate suppressing it.
        with patch.dict(os.environ, {"TRIAGE_MIN_TURNS": "0"}):
            agent = LLMAgent(client=mock_client)
            with caplog.at_level("INFO"):
                asyncio.run(agent.respond("I have a cold", [], lat=None, lng=None))

        grounding_records = [r for r in caplog.records if r.msg == "triage_grounding_checked"]
        assert len(grounding_records) == 1
        assert grounding_records[0].facility_provided is False
        assert grounding_records[0].grounded is None
