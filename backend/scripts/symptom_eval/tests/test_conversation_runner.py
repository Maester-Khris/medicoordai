import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from scripts.symptom_eval.conversation_runner import run_vignette_conversation
from scripts.symptom_eval.domain import Vignette
from scripts.symptom_eval.system_under_test import SystemTurnResult

VIGNETTE = Vignette(
    case_id="2", opening_message="I feel dizzy.", disclosure_items=[],
    gold_severity="emergent", gold_ctas_level=1,
)


class _ScriptedSystem:
    def __init__(self, results: list[SystemTurnResult]):
        self._results = results
        self.calls: list[tuple[str, list[dict]]] = []
        self.conversation_ids: list[str | None] = []

    def respond(self, patient_message, history, conversation_id=None):
        self.conversation_ids.append(conversation_id)
        self.calls.append((patient_message, list(history)))
        return self._results[len(self.calls) - 1]


class _ScriptedSimulator:
    def __init__(self, replies: list[str]):
        self._replies = replies
        self.calls = 0

    def reply(self, vignette, system_question, history):
        reply = self._replies[self.calls]
        self.calls += 1
        return reply


class TestRunVignetteConversation:
    def test_stops_at_first_triage_result(self):
        system = _ScriptedSystem([
            SystemTurnResult("How long?", None, None, False),
            SystemTurnResult("Go to the ER.", "emergent", "reasoning", False),
        ])
        simulator = _ScriptedSimulator(["An hour."])

        transcript = run_vignette_conversation(VIGNETTE, simulator, system, conversation_id="conv-1")

        assert transcript.final_severity == "emergent"
        assert len(transcript.turns) == 2
        assert transcript.turns[0].patient_message == "I feel dizzy."
        assert transcript.turns[1].patient_message == "An hour."
        assert simulator.calls == 1  # only asked for a reply once, before the triage turn

    def test_history_accumulates_across_turns(self):
        system = _ScriptedSystem([
            SystemTurnResult("How long?", None, None, False),
            SystemTurnResult("Go to the ER.", "emergent", "reasoning", False),
        ])
        simulator = _ScriptedSimulator(["An hour."])

        run_vignette_conversation(VIGNETTE, simulator, system, conversation_id="conv-1")

        second_call_history = system.calls[1][1]
        assert second_call_history == [
            {"role": "user", "content": "I feel dizzy."},
            {"role": "assistant", "content": "How long?"},
        ]


class TestConversationId:
    def test_every_turn_of_a_conversation_carries_the_same_id(self):
        system = _ScriptedSystem([
            SystemTurnResult("How long?", None, None, False),
            SystemTurnResult("Go to the ER.", "emergent", "reasoning", False),
        ])

        run_vignette_conversation(VIGNETTE, _ScriptedSimulator(["An hour."]), system, conversation_id="conv-1")

        assert system.conversation_ids == ["conv-1", "conv-1"]

    def test_a_turn_records_whether_the_cap_was_reached(self):
        system = _ScriptedSystem([SystemTurnResult("Go to the ER.", "emergent", "reasoning", False, cap_reached=True)])

        transcript = run_vignette_conversation(VIGNETTE, _ScriptedSimulator([]), system, conversation_id="conv-1")

        assert transcript.turns[0].cap_reached is True
