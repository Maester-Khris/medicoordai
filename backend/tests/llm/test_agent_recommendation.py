import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from unittest.mock import AsyncMock, MagicMock, patch

from services.llm_agent import LLMAgent

HERE = (43.6532, -79.3832)
A = {"id": "a", "name": "Alpha Clinic", "category": "ambulatory", "address": "1 Main St",
     "lat": 43.6596, "lng": -79.3884, "distanceKm": 0.8}
B = {"id": "b", "name": "Beta Clinic", "category": "ambulatory", "address": "2 Main St",
     "lat": 43.6800, "lng": -79.4000, "distanceKm": 3.3}
HISTORY = [
    {"role": "user", "content": "I have a sore throat"},
    {"role": "assistant", "content": "Since when?"},
    {"role": "user", "content": "Two days"},
    {"role": "assistant", "content": "Any fever?"},
    {"role": "user", "content": "A mild one"},
    {"role": "assistant", "content": "Trouble swallowing?"},
]


def _client(severity: str) -> MagicMock:
    classification = MagicMock(content=None, tool_calls=[{
        "id": "tc1", "name": "triage_response",
        "arguments": json.dumps({"severity": severity, "reasoning": "r", "information_sufficient": True}),
    }])
    answer = MagicMock(content="Please go to Beta Clinic.", tool_calls=None)
    client = MagicMock()
    client.chat = AsyncMock(side_effect=[classification, answer])
    return client


def test_the_agent_recommends_the_ranked_first_facility_and_counts_it() -> None:
    with patch("services.llm_agent.find_nearest_facilities", return_value=[A, B]), \
         patch("services.llm_agent.rank_facilities", return_value=[B, A]) as rank, \
         patch("services.llm_agent.facility_load.record") as record:
        result = asyncio.run(LLMAgent(client=_client("moderate")).respond("No", HISTORY, lat=HERE[0], lng=HERE[1]))

    assert result["turn_type"] == "triage"
    assert result["recommended_facility"] == B and result["nearby_facilities"] == [A]
    rank.assert_called_once_with([A, B], "moderate", HERE[0], HERE[1])
    record.assert_called_once_with(B, "moderate", HERE[0], HERE[1])


def test_without_a_location_nothing_is_ranked_or_counted() -> None:
    with patch("services.llm_agent.find_nearest_facilities") as find, \
         patch("services.llm_agent.rank_facilities") as rank, \
         patch("services.llm_agent.facility_load.record") as record:
        result = asyncio.run(LLMAgent(client=_client("moderate")).respond("No", HISTORY))

    assert result["recommended_facility"] is None
    find.assert_not_called()
    rank.assert_not_called()
    record.assert_not_called()
