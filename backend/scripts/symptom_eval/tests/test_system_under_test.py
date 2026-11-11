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
    @patch("scripts.symptom_eval.system_under_test.build_guarded_client")
    def test_respond_captures_graph_context_and_result_fields(
        self, mock_build_client, mock_agent_cls, mock_get_provider
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
                "nearby_facilities": [], "turn_type": "triage", "cap_reached": False,
            }

        mock_agent.respond = AsyncMock(side_effect=_respond_side_effect)
        mock_agent_cls.return_value = mock_agent

        adapter = LiveLLMAgentAdapter(graph_rag_provider="static")
        result = adapter.respond("I have chest pain", [], conversation_id="original:off:1:0")

        assert result.response_text == "Please go to the ER."
        assert result.severity == "emergent"
        assert result.graph_context_matched is True
        assert result.surfaced_red_flag_indicators == ["Shock"]
        assert result.surfaced_followup_questions == ["Are you feeling faint?"]
        assert os.environ["GRAPH_RAG_PROVIDER"] == "static"

    @patch("scripts.symptom_eval.system_under_test.get_graph_provider")
    @patch("scripts.symptom_eval.system_under_test.LLMAgent")
    @patch("scripts.symptom_eval.system_under_test.build_guarded_client")
    def test_the_system_runs_the_guard_stack_without_the_breaker_and_counts_spend_in_memory(
        self, mock_build_client, mock_agent_cls, mock_get_provider
    ):
        from llm.spend import InMemorySpendStore

        mock_get_provider.return_value = _StubProvider(MATCHED)
        mock_agent = MagicMock()
        mock_agent.respond = AsyncMock(return_value={
            "response": "Wrapping up.", "severity": "urgent", "reasoning": "r",
            "recommended_facility": None, "nearby_facilities": [], "turn_type": "triage", "cap_reached": True, "tokens_used": 321,
        })
        mock_agent_cls.return_value = mock_agent

        adapter = LiveLLMAgentAdapter(graph_rag_provider="off")
        result = adapter.respond("it hurts", [], conversation_id="lay:static:7:1")

        mock_build_client.assert_called_once_with("groq", breaker=False)
        assert isinstance(mock_agent_cls.call_args.kwargs["spend_store"], InMemorySpendStore)
        assert mock_agent.respond.call_args.kwargs["conversation_id"] == "lay:static:7:1"
        assert result.cap_reached is True
        assert result.tokens_used == 321


class TestEvalSystemProvider:
    """The system under test is Groq unless the run opts in with EVAL_SYSTEM_PROVIDER=openai
    (any OpenAI-compatible host, for example Ollama Cloud, through OPENAI_BASE_URL)."""

    @patch("scripts.symptom_eval.system_under_test.get_graph_provider")
    @patch("scripts.symptom_eval.system_under_test.LLMAgent")
    @patch("scripts.symptom_eval.system_under_test.build_guarded_client")
    def test_the_provider_defaults_to_groq_and_can_be_switched_to_openai(
        self, mock_build_client, mock_agent_cls, mock_get_provider, monkeypatch
    ):
        monkeypatch.delenv("EVAL_SYSTEM_PROVIDER", raising=False)
        LiveLLMAgentAdapter(graph_rag_provider="off")
        mock_build_client.assert_called_with("groq", breaker=False)

        monkeypatch.setenv("EVAL_SYSTEM_PROVIDER", "openai")
        LiveLLMAgentAdapter(graph_rag_provider="off")
        mock_build_client.assert_called_with("openai", breaker=False)

    def test_an_unknown_provider_is_refused_instead_of_falling_back_to_groq(self, monkeypatch):
        import pytest
        from scripts.symptom_eval.system_under_test import eval_system_provider

        monkeypatch.setenv("EVAL_SYSTEM_PROVIDER", "anthropic")
        with pytest.raises(ValueError, match="EVAL_SYSTEM_PROVIDER"):
            eval_system_provider()

    def test_the_manifest_label_names_the_model_and_the_host_for_openai_compatible_runs(self, monkeypatch):
        from scripts.symptom_eval.system_under_test import eval_system_model_label

        monkeypatch.setenv("EVAL_SYSTEM_PROVIDER", "openai")
        monkeypatch.setenv("OPENAI_MODEL", "gpt-oss:120b-cloud")
        monkeypatch.setenv("OPENAI_BASE_URL", "http://localhost:11434/v1")
        assert eval_system_model_label() == "gpt-oss:120b-cloud via http://localhost:11434/v1"

        monkeypatch.delenv("OPENAI_BASE_URL")
        assert eval_system_model_label() == "gpt-oss:120b-cloud via api.openai.com"

    def test_the_groq_label_stays_the_bare_model_name_so_older_manifests_still_match(self, monkeypatch):
        from scripts.symptom_eval.system_under_test import eval_system_model_label

        monkeypatch.delenv("EVAL_SYSTEM_PROVIDER", raising=False)
        monkeypatch.setenv("GROQ_API_KEY", "test")
        monkeypatch.setenv("GROQ_MODEL", "openai/gpt-oss-120b")
        assert eval_system_model_label() == "openai/gpt-oss-120b"
