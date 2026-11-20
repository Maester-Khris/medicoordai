import asyncio
import json
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

import pytest

from llm.base import BaseLLMClient, LLMResponse
from llm.spend import InMemorySpendStore
from services.llm_agent import LLMAgent, capped_reply, escalate

ORDER = ["routine", "moderate", "urgent", "emergent"]
NEUTRAL_HISTORY = [
    {"role": "user", "content": "I feel unwell"}, {"role": "assistant", "content": "Since when?"},
    {"role": "user", "content": "an hour"}, {"role": "assistant", "content": "Anything else?"},
    {"role": "user", "content": "just tired"}, {"role": "assistant", "content": "Okay."},
]
CHEST = "I have chest pain"


def _triage(severity: str) -> LLMResponse:
    call = {"id": "1", "name": "triage_response",
            "arguments": json.dumps({"severity": severity, "reasoning": "model reasoning", "information_sufficient": True})}
    return LLMResponse(content=None, tool_calls=[call], finish_reason="tool_calls", model="fake", usage={})


def _text(content: str) -> LLMResponse:
    return LLMResponse(content=content, tool_calls=None, finish_reason="stop", model="fake", usage={})


class _Scripted(BaseLLMClient):
    def __init__(self, *responses: LLMResponse) -> None:
        self._responses = list(responses)
        self.calls = 0

    @property
    def model_name(self) -> str:
        return "fake"

    async def chat(self, messages, tools=None, temperature=0.2, stop=None, force_tool=None) -> LLMResponse:
        self.calls += 1
        return self._responses[min(self.calls, len(self._responses)) - 1]


def _respond(client: _Scripted, message: str, history: list[dict], **kwargs) -> dict:
    return asyncio.run(LLMAgent(client=client, **kwargs.pop("agent", {})).respond(message, history, **kwargs))


def _records(caplog: pytest.LogCaptureFixture, name: str) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.message == name]


@pytest.mark.parametrize("severity", ORDER)
def test_escalate_never_lowers_a_severity(severity: str) -> None:
    assert escalate(severity, flagged=False) == severity
    assert escalate(severity, flagged=True) == "emergent"
    assert ORDER.index(escalate(severity, flagged=True)) >= ORDER.index(severity)


def test_enforce_answers_a_red_flag_on_the_first_turn_without_classifying(monkeypatch, caplog) -> None:
    monkeypatch.setenv("RED_FLAG_FLOOR_MODE", "enforce")
    client = _Scripted(_text("Please stay calm and go to the nearest emergency department."))
    with caplog.at_level(logging.INFO, logger="services.llm_agent"):
        result = _respond(client, CHEST, [])
    assert (result["severity"], result["turn_type"], result["cap_reached"]) == ("emergent", "triage", False)
    assert result["reasoning"] == "red-flag floor: chest_pain"
    assert client.calls == 1  # the reply only: the classification call is skipped
    assert "911" in result["response"] and ("211" not in result["response"] or result["response"].index("911") < result["response"].index("211"))
    applied = _records(caplog, "red_flag_floor_applied")
    assert len(applied) == 1 and applied[0].categories == ["chest_pain"]


def test_enforce_finds_a_red_flag_disclosed_on_an_earlier_turn(monkeypatch) -> None:
    monkeypatch.setenv("RED_FLAG_FLOOR_MODE", "enforce")
    history = [{"role": "user", "content": CHEST}, {"role": "assistant", "content": "How long?"}]
    client = _Scripted(_text("Go to the emergency department."))
    result = _respond(client, "about an hour", history)
    assert result["severity"] == "emergent" and client.calls == 1


def test_enforce_on_a_capped_conversation_makes_no_model_call_and_uses_the_template(monkeypatch) -> None:
    monkeypatch.setenv("RED_FLAG_FLOOR_MODE", "enforce")
    monkeypatch.setenv("LLM_CONVERSATION_TOKEN_CAP", "1000")
    store = InMemorySpendStore()
    asyncio.run(store.add("c1", 1000))
    client = _Scripted(_text("unused"))
    result = _respond(client, CHEST, [], conversation_id="c1", agent={"spend_store": store})
    assert client.calls == 0 and result["cap_reached"] is True
    assert result["response"] == capped_reply("emergent", None)


def test_enforce_without_a_red_flag_takes_the_normal_path(monkeypatch) -> None:
    monkeypatch.setenv("RED_FLAG_FLOOR_MODE", "enforce")
    client = _Scripted(_triage("urgent"), _text("Please see a clinic today."))
    result = _respond(client, "my stomach hurts", NEUTRAL_HISTORY)
    assert (result["severity"], client.calls) == ("urgent", 2)


def test_shadow_logs_what_it_would_do_and_changes_nothing(monkeypatch, caplog) -> None:
    monkeypatch.setenv("RED_FLAG_FLOOR_MODE", "shadow")
    client = _Scripted(_triage("moderate"), _text("See a doctor soon."))
    with caplog.at_level(logging.INFO, logger="services.llm_agent"):
        result = _respond(client, CHEST, NEUTRAL_HISTORY)
    assert result["severity"] == "moderate" and client.calls == 2
    shadow = _records(caplog, "red_flag_floor_shadow")
    assert len(shadow) == 1
    assert (shadow[0].categories, shadow[0].model_severity, shadow[0].would_escalate) == (["chest_pain"], "moderate", True)
    assert "chest pain" not in str(shadow[0].__dict__)  # category ids only, never the patient's words


def test_shadow_says_no_escalation_when_the_model_already_said_emergent(monkeypatch, caplog) -> None:
    monkeypatch.setenv("RED_FLAG_FLOOR_MODE", "shadow")
    client = _Scripted(_triage("emergent"), _text("Call 911 now."))
    with caplog.at_level(logging.INFO, logger="services.llm_agent"):
        _respond(client, CHEST, NEUTRAL_HISTORY)
    assert _records(caplog, "red_flag_floor_shadow")[0].would_escalate is False


def test_shadow_counts_a_follow_up_turn_as_one_the_floor_would_have_escalated(monkeypatch, caplog) -> None:
    monkeypatch.setenv("RED_FLAG_FLOOR_MODE", "shadow")
    client = _Scripted(_text("How long has this been going on?"))
    with caplog.at_level(logging.INFO, logger="services.llm_agent"):
        result = _respond(client, CHEST, [])
    assert result["severity"] is None
    record = _records(caplog, "red_flag_floor_shadow")[0]
    assert (record.model_severity, record.would_escalate) == (None, True)


def test_off_does_not_look_and_changes_nothing(monkeypatch, caplog) -> None:
    monkeypatch.setenv("RED_FLAG_FLOOR_MODE", "off")
    client = _Scripted(_triage("moderate"), _text("See a doctor soon."))
    with caplog.at_level(logging.INFO, logger="services.llm_agent"):
        result = _respond(client, CHEST, NEUTRAL_HISTORY)
    assert result["severity"] == "moderate"
    assert _records(caplog, "red_flag_floor_shadow") == [] and _records(caplog, "red_flag_floor_applied") == []


def test_the_default_mode_is_shadow(monkeypatch, caplog) -> None:
    monkeypatch.delenv("RED_FLAG_FLOOR_MODE", raising=False)
    client = _Scripted(_triage("moderate"), _text("See a doctor soon."))
    with caplog.at_level(logging.INFO, logger="services.llm_agent"):
        result = _respond(client, CHEST, NEUTRAL_HISTORY)
    assert result["severity"] == "moderate" and len(_records(caplog, "red_flag_floor_shadow")) == 1
