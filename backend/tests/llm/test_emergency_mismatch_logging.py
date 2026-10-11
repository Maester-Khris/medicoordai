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
