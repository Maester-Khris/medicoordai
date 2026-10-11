import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from graph.base import GraphContext, GraphContextProvider, RedFlagMatch
from scripts.symptom_eval.system_under_test import LiveLLMAgentAdapter


class _StubProvider(GraphContextProvider):
    def __init__(self, context):
        self._context = context

    def _lookup(self, user_message, recent_messages):
        return self._context


MATCHED = GraphContext(
    matched=True, complaint_name="Chest pain (cardiac features)",
    red_flags=[RedFlagMatch("Shock", 1, "emergent", "Are you feeling faint?")],
)


class TestLiveLLMAgentAdapter:
    @patch("scripts.symptom_eval.system_under_test.get_graph_provider")
    @patch("scripts.symptom_eval.system_under_test.LLMAgent")
    @patch("scripts.symptom_eval.system_under_test.GroqClient")
    def test_respond_captures_graph_context_and_result_fields(
        self, mock_groq_cls, mock_agent_cls, mock_get_provider
    ):
        mock_get_provider.return_value = _StubProvider(MATCHED)
        mock_agent = MagicMock()

        def _respond_side_effect(user_message, history, **kwargs):
            # Real LLMAgent.respond() calls its injected graph_provider
            # internally (services/llm_agent.py:100) — replicate that here
            # since LLMAgent itself is mocked out below.
            graph_provider = mock_agent_cls.call_args.kwargs["graph_provider"]
            graph_provider.get_symptom_graph_context(user_message, history)
            return {
                "response": "Please go to the ER.", "severity": "emergent",
                "reasoning": "chest pain with shock signs", "recommended_facility": None,
                "nearby_facilities": [], "turn_type": "triage",
            }

        mock_agent.respond = AsyncMock(side_effect=_respond_side_effect)
        mock_agent_cls.return_value = mock_agent

        adapter = LiveLLMAgentAdapter(graph_rag_provider="static")
        result = adapter.respond("I have chest pain", [])

        assert result.response_text == "Please go to the ER."
        assert result.severity == "emergent"
        assert result.graph_context_matched is True
        assert result.surfaced_red_flag_indicators == ["Shock"]
        assert result.surfaced_followup_questions == ["Are you feeling faint?"]
        assert os.environ["GRAPH_RAG_PROVIDER"] == "static"
