import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from unittest.mock import patch

import pytest

from llm.base import BaseLLMClient, LLMResponse
from llm.spend import InMemorySpendStore, RedisSpendStore
from observability import _registry
from services import llm_agent
from services.llm_agent import CAPPED_NOTE, SAFETY_LINE, LLMAgent, capped_reply

CAP = 1000
THREE_USER_TURNS = [
    {"role": "user", "content": "my chest hurts"}, {"role": "assistant", "content": "Since when?"},
    {"role": "user", "content": "an hour"}, {"role": "assistant", "content": "Any other symptoms?"},
    {"role": "user", "content": "no"}, {"role": "assistant", "content": "Okay."},
]
FACILITY = {"name": "Test General Hospital", "address": "1 Main St", "distanceKm": 2.5}


def _triage(severity: str = "urgent", usage: tuple[int, int] = (100, 20)) -> LLMResponse:
    call = {"id": "1", "name": "triage_response",
            "arguments": json.dumps({"severity": severity, "reasoning": "r", "information_sufficient": True})}
    return LLMResponse(content=None, tool_calls=[call], finish_reason="tool_calls", model="fake",
                       usage={"prompt_tokens": usage[0], "completion_tokens": usage[1]})


def _text(content: str, usage: tuple[int, int] = (50, 10)) -> LLMResponse:
    return LLMResponse(content=content, tool_calls=None, finish_reason="stop", model="fake",
                       usage={"prompt_tokens": usage[0], "completion_tokens": usage[1]})


class _Scripted(BaseLLMClient):
    def __init__(self, *responses: LLMResponse) -> None:
        self._responses = list(responses)
        self.calls: list[dict] = []

    @property
    def model_name(self) -> str:
        return "fake"

    async def chat(self, messages, tools=None, temperature=0.2, stop=None, force_tool=None) -> LLMResponse:
        self.calls.append({"tools": tools, "force_tool": force_tool})
        return self._responses[min(len(self.calls), len(self._responses)) - 1]


@pytest.fixture(autouse=True)
def _cap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_CONVERSATION_TOKEN_CAP", str(CAP))


def _run(agent: LLMAgent, history: list[dict], **kwargs) -> dict:
    return asyncio.run(agent.respond("it is getting worse", history, **kwargs))


def _store_at(tokens: int, conversation_id: str = "c1") -> InMemorySpendStore:
    store = InMemorySpendStore()
    asyncio.run(store.add(conversation_id, tokens))
    return store


def test_under_the_cap_the_turn_is_unchanged_and_every_call_is_counted() -> None:
    client, store = _Scripted(_triage(usage=(100, 20)), _text("Go to the clinic.", usage=(50, 10))), InMemorySpendStore()
    result = _run(LLMAgent(client=client, spend_store=store), THREE_USER_TURNS, conversation_id="c1")
    assert (result["turn_type"], result["severity"], result["cap_reached"]) == ("triage", "urgent", False)
    assert result["response"] == "Go to the clinic."
    assert len(client.calls) == 2
    assert asyncio.run(store.total("c1")) == 180
    assert result["tokens_used"] == 180  # the turn reports what it spent, classify call plus reply call


def test_without_a_conversation_id_nothing_is_counted_and_no_cap_applies() -> None:
    client, store = _Scripted(_triage(), _text("Go to the clinic.")), _store_at(10 * CAP)
    result = _run(LLMAgent(client=client, spend_store=store), THREE_USER_TURNS)
    assert result["cap_reached"] is False and len(client.calls) == 2
    assert asyncio.run(store.total("c1")) == 10 * CAP


def test_without_a_spend_store_no_cap_applies() -> None:
    client = _Scripted(_triage(), _text("Go to the clinic."))
    result = _run(LLMAgent(client=client), THREE_USER_TURNS, conversation_id="c1")
    assert result["cap_reached"] is False and len(client.calls) == 2


def _cap_reached_count() -> float:
    return _registry.get_sample_value("llm_cap_reached_total") or 0.0


def test_at_the_cap_the_turn_is_forced_to_classify_with_one_call_and_a_templated_reply() -> None:
    client, store = _Scripted(_triage("urgent")), _store_at(CAP)
    before = _cap_reached_count()
    result = _run(LLMAgent(client=client, spend_store=store), [], conversation_id="c1")  # zero user turns: below the minimum
    assert len(client.calls) == 1
    assert client.calls[0]["force_tool"] == "triage_response"
    assert (result["turn_type"], result["severity"], result["cap_reached"]) == ("triage", "urgent", True)
    assert result["response"] == capped_reply("urgent", None)
    assert CAPPED_NOTE in result["response"]
    assert _cap_reached_count() == before + 1
    assert result["tokens_used"] == 120  # one call only: the templated reply costs nothing


def test_the_capped_reply_names_the_recommended_facility() -> None:
    client, store = _Scripted(_triage("urgent")), _store_at(CAP)
    with patch.object(llm_agent, "find_nearest_facilities", return_value=[FACILITY]), \
         patch.object(llm_agent, "rank_facilities", return_value=[FACILITY]), \
         patch.object(llm_agent.facility_load, "record"):
        result = _run(LLMAgent(client=client, spend_store=store), [], conversation_id="c1", lat=43.65, lng=-79.38)
    assert result["recommended_facility"] == FACILITY
    assert FACILITY["name"] in result["response"]
    assert len(client.calls) == 1


def test_the_capped_reply_for_an_emergency_mentions_911_and_without_a_facility_mentions_211() -> None:
    assert "911" in capped_reply("emergent", FACILITY)
    assert "211" in capped_reply("routine", None)
    assert CAPPED_NOTE in capped_reply("moderate", FACILITY)


def test_at_the_cap_a_model_that_does_not_classify_gets_the_safety_line_and_no_severity() -> None:
    client, store = _Scripted(_text("Tell me more.")), _store_at(CAP)
    result = _run(LLMAgent(client=client, spend_store=store), [], conversation_id="c1")
    assert (result["turn_type"], result["severity"], result["cap_reached"]) == ("followup", None, True)
    assert SAFETY_LINE in result["response"]
    assert result["recommended_facility"] is None


def test_the_cap_is_per_conversation() -> None:
    client, store = _Scripted(_text("Since when?")), _store_at(CAP, "other-conversation")
    result = _run(LLMAgent(client=client, spend_store=store), [], conversation_id="c1")
    assert result["cap_reached"] is False


def test_a_broken_counter_does_not_stop_the_agent() -> None:
    class _BrokenRedis:
        def incrby(self, key, amount):
            raise ConnectionError("down")

        def expire(self, key, seconds):
            raise ConnectionError("down")

        def get(self, key):
            raise ConnectionError("down")

    client = _Scripted(_triage(), _text("Go to the clinic."))
    result = _run(LLMAgent(client=client, spend_store=RedisSpendStore(_BrokenRedis())), THREE_USER_TURNS,
                  conversation_id="c1")
    assert (result["turn_type"], result["cap_reached"]) == ("triage", False)


def test_the_safety_line_names_911_and_211() -> None:
    assert "911" in SAFETY_LINE and "211" in SAFETY_LINE


def test_tokens_are_reported_even_without_a_conversation_id() -> None:
    client = _Scripted(_text("Since when?", usage=(70, 5)))
    result = _run(LLMAgent(client=client), [])
    assert result["tokens_used"] == 75


def test_two_turns_do_not_share_a_token_count() -> None:
    agent = LLMAgent(client=_Scripted(_text("Since when?", usage=(70, 5))))
    assert _run(agent, [])["tokens_used"] == 75
    assert _run(agent, [])["tokens_used"] == 75
