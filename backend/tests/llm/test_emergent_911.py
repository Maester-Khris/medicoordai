import asyncio
import json
import os
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from llm.base import LLMResponse
from services.llm_agent import EMERGENT_OPENER, LLMAgent


def _agent(severity: str, reply: str) -> LLMAgent:
    tool = LLMResponse(content=None, finish_reason="tool_calls", model="t", usage={}, tool_calls=[{
        "name": "triage_response",
        "arguments": json.dumps({"severity": severity, "reasoning": "r", "information_sufficient": True})}])
    text = LLMResponse(content=reply, tool_calls=None, finish_reason="stop", model="t", usage={})
    client = MagicMock()
    client.chat = AsyncMock(side_effect=[tool, text])
    return LLMAgent(client=client)


def _respond(agent: LLMAgent) -> dict:
    history = [{"role": "user" if i % 2 == 0 else "assistant", "content": "x"} for i in range(6)]
    return asyncio.run(agent.respond("crushing chest pain", history=history))


@pytest.mark.parametrize("reply", [
    "Please call 211 right away to get emergency assistance.",              # the real no-location reply
    "Please go immediately to Test General Hospital.",                      # no number at all
    "Call emergency services right away.",                                  # no number
])
def test_an_emergent_reply_without_911_gets_the_911_line_first(reply):
    out = _respond(_agent("emergent", reply))["response"]
    assert out == f"{EMERGENT_OPENER} {reply}"


def test_an_emergent_reply_that_already_says_911_is_unchanged():
    reply = "Please call 911 and go to Test General Hospital."
    assert _respond(_agent("emergent", reply))["response"] == reply


@pytest.mark.parametrize("severity", ["routine", "moderate", "urgent"])
def test_other_severities_are_unchanged(severity):
    reply = "Please book a visit with your doctor."
    assert _respond(_agent(severity, reply))["response"] == reply
