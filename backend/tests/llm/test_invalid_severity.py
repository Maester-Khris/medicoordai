import asyncio
import json
import logging
import os
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from llm.base import LLMResponse
from services.llm_agent import LLMAgent


def _triage(severity: str) -> LLMResponse:
    return LLMResponse(
        content=None,
        tool_calls=[{"name": "triage_response", "arguments": json.dumps(
            {"severity": severity, "reasoning": "test", "information_sufficient": True})}],
        finish_reason="tool_calls", model="test", usage={},
    )


@pytest.mark.parametrize("bad", ["critical", "severe", "high", "low", "EMERGENT", "", "emergent; drop"])
def test_a_severity_outside_the_four_values_fails_toward_emergent(bad, caplog):
    client = MagicMock()
    client.chat = AsyncMock(side_effect=[
        _triage(bad),
        LLMResponse(content="Please call 911.", tool_calls=None, finish_reason="stop", model="test", usage={}),
    ])
    with caplog.at_level(logging.WARNING, logger="services.llm_agent"):
        result = asyncio.run(LLMAgent(client=client).respond("chest pain", history=[]))

    assert result["severity"] == "emergent"          # not held back, not passed through
    assert result["turn_type"] == "triage"
    assert [r for r in caplog.records if r.message == "triage_invalid_severity"]


@pytest.mark.parametrize("good", ["routine", "moderate", "urgent", "emergent"])
def test_the_four_valid_severities_are_unchanged(good):
    client = MagicMock()
    client.chat = AsyncMock(side_effect=[
        _triage(good),
        LLMResponse(content="ok", tool_calls=None, finish_reason="stop", model="test", usage={}),
    ])
    history = [{"role": "user" if i % 2 == 0 else "assistant", "content": "x"} for i in range(6)]
    result = asyncio.run(LLMAgent(client=client).respond("chest pain", history=history))
    assert result["severity"] == good
