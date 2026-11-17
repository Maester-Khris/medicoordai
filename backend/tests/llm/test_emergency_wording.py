import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

import pytest

from llm.base import BaseLLMClient, LLMResponse
from services.llm_agent import (
    CAPPED_NO_RESULT,
    EMERGENT_OPENER,
    SAFETY_LINE,
    LLMAgent,
    capped_reply,
    capped_reply_fingerprint,
    ensure_911_first,
    facility_fact,
)

FACILITY = {"name": "Test General Hospital", "address": "1 Main St", "distanceKm": 2.0}


def _911_before_211(text: str) -> bool:
    return "911" in text and ("211" not in text or text.index("911") < text.index("211"))


def test_an_emergent_reply_with_no_911_gets_the_opener_first() -> None:
    out = ensure_911_first("Go to the hospital.", "emergent")
    assert out.startswith(EMERGENT_OPENER) and out.endswith("Go to the hospital.")


def test_an_emergent_reply_that_says_211_before_911_gets_the_opener_first() -> None:
    out = ensure_911_first("Call 211 for help, or call 911 if it gets worse.", "emergent")
    assert out.startswith(EMERGENT_OPENER) and _911_before_211(out)


def test_an_emergent_reply_that_already_has_911_first_is_unchanged() -> None:
    text = "Call 911 now. You can also call 211 later."
    assert ensure_911_first(text, "emergent") == text


@pytest.mark.parametrize("severity", ["routine", "moderate", "urgent"])
def test_other_severities_are_never_touched(severity: str) -> None:
    assert ensure_911_first("Rest at home.", severity) == "Rest at home."


@pytest.mark.parametrize("text", [
    SAFETY_LINE,
    CAPPED_NO_RESULT,
    capped_reply("emergent", FACILITY),
    capped_reply("emergent", None),
])
def test_every_fixed_emergent_text_puts_911_before_211(text: str) -> None:
    assert _911_before_211(text)


def test_the_no_facility_emergent_prompt_does_not_send_the_patient_to_211() -> None:
    fact = facility_fact(None, "emergent")
    assert "211" not in fact and "911" in fact


def test_the_no_facility_non_emergent_prompt_keeps_the_211_line() -> None:
    assert "211" in facility_fact(None, "moderate")


def test_the_facility_prompt_names_the_facility() -> None:
    assert "Test General Hospital" in facility_fact(FACILITY, "emergent")


def test_the_fingerprint_covers_the_opener_and_the_emergent_texts() -> None:
    fingerprint = capped_reply_fingerprint()
    assert EMERGENT_OPENER in fingerprint
    assert facility_fact(None, "emergent") in fingerprint
    assert capped_reply("emergent", None) in fingerprint


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


def test_an_agent_reply_that_sends_the_patient_to_211_first_is_fixed() -> None:
    triage = LLMResponse(
        content=None, finish_reason="tool_calls", model="fake", usage={},
        tool_calls=[{"name": "triage_response", "arguments": json.dumps(
            {"severity": "emergent", "reasoning": "r", "information_sufficient": True})}],
    )
    reply = LLMResponse(content="Please call 211 for help.", tool_calls=None, finish_reason="stop", model="fake", usage={})
    result = asyncio.run(LLMAgent(client=_Scripted(triage, reply)).respond("it hurts", history=[]))
    assert result["severity"] == "emergent" and _911_before_211(result["response"])
