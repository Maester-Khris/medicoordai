# backend/tests/llm/test_emergency_mismatch_logging.py
import logging
import asyncio
import os
import sys
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from llm.base import LLMResponse
from services.llm_agent import LLMAgent


def _triage_response(severity: str) -> LLMResponse:
    import json
    return LLMResponse(
        content=None,
        tool_calls=[{
            "name": "triage_response",
            "arguments": json.dumps({
                "severity": severity, "reasoning": "test",
                "information_sufficient": True,
            }),
        }],
        finish_reason="tool_calls", model="test", usage={},
    )


class TestEmergencyMismatchLogging:
    def test_logs_mismatch_without_changing_severity(self, caplog):
        client = MagicMock()
        client.chat = AsyncMock(side_effect=[
            _triage_response("routine"),
            LLMResponse(content="ok", tool_calls=None, finish_reason="stop", model="test", usage={}),
        ])
        agent = LLMAgent(client=client)

        with caplog.at_level(logging.WARNING, logger="services.llm_agent"):
            # 3 prior user turns clears TRIAGE_MIN_TURNS (default 3) so a
            # "routine" (non-emergent) classification isn't suppressed
            # before _handle_triage runs the emergency cross-check.
            result = asyncio.run(agent.respond("I have chest pain", history=[
                {"role": "user", "content": "a"}, {"role": "assistant", "content": "b"},
                {"role": "user", "content": "c"}, {"role": "assistant", "content": "d"},
                {"role": "user", "content": "e"}, {"role": "assistant", "content": "f"},
            ]))

        assert result["severity"] == "routine"
        mismatches = [r for r in caplog.records if r.message == "emergency_mismatch_detected"]
        assert len(mismatches) == 1


from services.llm_agent import capped_reply

NEUTRAL_THREE_TURNS = [
    {"role": "user", "content": "I feel unwell"}, {"role": "assistant", "content": "b"},
    {"role": "user", "content": "an hour"}, {"role": "assistant", "content": "d"},
    {"role": "user", "content": "just tired"}, {"role": "assistant", "content": "f"},
]


def _agent_saying(severity: str) -> tuple[LLMAgent, MagicMock]:
    client = MagicMock()
    client.chat = AsyncMock(side_effect=[
        _triage_response(severity),
        LLMResponse(content="ok", tool_calls=None, finish_reason="stop", model="test", usage={}),
    ])
    return LLMAgent(client=client), client


def _mismatches(caplog) -> list:
    return [r for r in caplog.records if r.message == "emergency_mismatch_detected"]


class TestEmergencyMismatchModes:
    def test_enforce_escalates_to_emergent_with_the_template_and_no_reply_call(self, monkeypatch) -> None:
        monkeypatch.setenv("EMERGENCY_MISMATCH_MODE", "enforce")
        agent, client = _agent_saying("routine")
        result = asyncio.run(agent.respond("I have chest pain", NEUTRAL_THREE_TURNS))
        assert result["severity"] == "emergent"
        assert client.chat.await_count == 1  # classification only: the reply is the template
        assert result["response"] == capped_reply("emergent", None, capped=False)
        assert "911" in result["response"]

    def test_enforce_finds_a_red_flag_from_an_earlier_turn(self, monkeypatch) -> None:
        monkeypatch.setenv("EMERGENCY_MISMATCH_MODE", "enforce")
        history = [{"role": "user", "content": "I have chest pain"}, {"role": "assistant", "content": "b"}] + NEUTRAL_THREE_TURNS
        agent, _ = _agent_saying("moderate")
        assert asyncio.run(agent.respond("still the same", history))["severity"] == "emergent"

    def test_a_negated_mention_is_not_a_mismatch(self, monkeypatch, caplog) -> None:
        monkeypatch.setenv("EMERGENCY_MISMATCH_MODE", "enforce")
        agent, _ = _agent_saying("routine")
        with caplog.at_level(logging.WARNING, logger="services.llm_agent"):
            result = asyncio.run(agent.respond("I have a cough but no chest pain", NEUTRAL_THREE_TURNS))
        assert result["severity"] == "routine" and _mismatches(caplog) == []

    def test_shadow_logs_categories_and_changes_nothing(self, monkeypatch, caplog) -> None:
        monkeypatch.setenv("EMERGENCY_MISMATCH_MODE", "shadow")
        agent, _ = _agent_saying("routine")
        with caplog.at_level(logging.WARNING, logger="services.llm_agent"):
            result = asyncio.run(agent.respond("I have chest pain", NEUTRAL_THREE_TURNS))
        assert result["severity"] == "routine"
        assert _mismatches(caplog)[0].categories == ["chest_pain"]

    def test_off_does_not_look(self, monkeypatch, caplog) -> None:
        monkeypatch.setenv("EMERGENCY_MISMATCH_MODE", "off")
        agent, _ = _agent_saying("routine")
        with caplog.at_level(logging.WARNING, logger="services.llm_agent"):
            result = asyncio.run(agent.respond("I have chest pain", NEUTRAL_THREE_TURNS))
        assert result["severity"] == "routine" and _mismatches(caplog) == []
