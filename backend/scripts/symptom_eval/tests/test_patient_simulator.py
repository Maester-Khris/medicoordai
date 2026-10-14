import os
import sys
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from llm.base import LLMResponse
from scripts.symptom_eval.domain import ConversationTurn, DisclosureItem, Vignette
from scripts.symptom_eval.patient_simulator import AnthropicPatientSimulator

VIGNETTE = Vignette(
    case_id="2",
    opening_message="I feel dizzy and almost fainted.",
    disclosure_items=[
        DisclosureItem("syncope_duration", "history", "It lasted a few seconds.", True),
        DisclosureItem("no_chest_pain", "history", "No, I don't have chest pain.", True),
    ],
    gold_severity="emergent",
    gold_ctas_level=1,
)


class TestAnthropicPatientSimulator:
    def test_reply_returns_client_content(self):
        client = MagicMock()
        client.chat = AsyncMock(return_value=LLMResponse(
            content="It lasted a few seconds.", tool_calls=None,
            finish_reason="stop", model="claude-haiku-4-5", usage={},
        ))
        simulator = AnthropicPatientSimulator(client=client)

        reply = simulator.reply(VIGNETTE, "How long did the dizziness last?", history=[])

        assert reply == "It lasted a few seconds."

    def test_checklist_in_system_prompt_excludes_already_disclosed_items(self):
        client = MagicMock()
        client.chat = AsyncMock(return_value=LLMResponse(
            content="ok", tool_calls=None, finish_reason="stop", model="x", usage={},
        ))
        VIGNETTE.disclosure_items[0].disclosed = True
        simulator = AnthropicPatientSimulator(client=client)

        simulator.reply(VIGNETTE, "Anything else?", history=[])

        system_prompt = client.chat.call_args.kwargs["messages"][0].content
        assert "No, I don't have chest pain." in system_prompt
        assert "It lasted a few seconds." not in system_prompt
        VIGNETTE.disclosure_items[0].disclosed = False  # reset for other tests

    def test_history_and_question_included_as_conversation(self):
        client = MagicMock()
        client.chat = AsyncMock(return_value=LLMResponse(
            content="ok", tool_calls=None, finish_reason="stop", model="x", usage={},
        ))
        simulator = AnthropicPatientSimulator(client=client)
        history = [
            ConversationTurn(0, "I feel dizzy.", "How long has this been going on?", False, [], []),
        ]

        simulator.reply(VIGNETTE, "Any chest pain?", history=history)

        messages = client.chat.call_args.kwargs["messages"]
        contents = [m.content for m in messages]
        assert "How long has this been going on?" in contents
        assert "I feel dizzy." in contents
        assert "Any chest pain?" in contents
