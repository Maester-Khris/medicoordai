"""
SystemUnderTestPort + LiveLLMAgentAdapter — wraps the real LLMAgent
in-process (design §2: same business behavior as the HTTP path, no
server/auth/cache needed). Builds its client directly (not
get_llm_client(), which would respect an ambient LLM_PROVIDER override) so
the system-under-test model is Groq — the production default
(backend/services/llm_agent.py:20) — regardless of environment, per the
model-role assignment in design §5, unless the run opts in with
EVAL_SYSTEM_PROVIDER=openai (see eval_system_provider). Wraps the real GraphContextProvider in
CapturingGraphProvider (Task 2) so each call's GraphContext is observable.
"""
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from graph.factory import get_graph_provider
from llm.spend import InMemorySpendStore
from llm.sync import run_sync
from services.llm_agent import LLMAgent, build_guarded_client
from scripts.symptom_eval.graph_capture import CapturingGraphProvider


@dataclass
class SystemTurnResult:
    response_text: str
    severity: str | None
    reasoning: str | None
    graph_context_matched: bool
    surfaced_red_flag_indicators: list[str] = field(default_factory=list)
    surfaced_followup_questions: list[str] = field(default_factory=list)
    cap_reached: bool = False
    tokens_used: int = 0


class SystemUnderTestPort(ABC):
    @abstractmethod
    def respond(self, patient_message: str, history: list[dict], conversation_id: str) -> SystemTurnResult:
        ...


# The breaker only acts during a provider outage. In the eval an outage must fail the conversation
# loudly (the checkpoint resume reruns it), not turn paid conversations into silent 'unclassified'
# results. Retry and the spend cap change answers on a healthy provider, so they run (spec C11).
EVAL_BREAKER_ENABLED = False


def eval_system_provider() -> str:
    """Groq (the production host) unless the run opts in with EVAL_SYSTEM_PROVIDER=openai, which
    reaches any OpenAI-compatible host through OPENAI_BASE_URL (for example Ollama Cloud, when the
    Groq free tier's daily limit is too slow). Anything else is refused, never silently Groq."""
    provider = os.environ.get("EVAL_SYSTEM_PROVIDER", "groq").strip().lower()
    if provider not in ("groq", "openai"):
        raise ValueError(f"EVAL_SYSTEM_PROVIDER must be groq or openai, got {provider!r}")
    return provider


def eval_system_model_label() -> str:
    """What the run manifest records as the system model. Groq keeps the bare model name so older
    manifests still match; an OpenAI-compatible run also names its host, because the same weights
    served elsewhere can answer differently."""
    if eval_system_provider() == "groq":
        return os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")
    host = os.environ.get("OPENAI_BASE_URL") or "api.openai.com"
    return f"{os.environ['OPENAI_MODEL']} via {host}"


class LiveLLMAgentAdapter(SystemUnderTestPort):
    def __init__(self, graph_rag_provider: str = "off"):
        os.environ["GRAPH_RAG_PROVIDER"] = graph_rag_provider
        # Evaluation runs must not depend on a random pick or write counters to the shared Redis.
        os.environ["LOAD_AWARE_ROUTING"] = "off"
        self._capturing_provider = CapturingGraphProvider(get_graph_provider())
        self._agent = LLMAgent(
            client=build_guarded_client(eval_system_provider(), breaker=EVAL_BREAKER_ENABLED),
            graph_provider=self._capturing_provider,
            spend_store=InMemorySpendStore(),
        )

    def respond(self, patient_message: str, history: list[dict], conversation_id: str) -> SystemTurnResult:
        result = run_sync(self._agent.respond(patient_message, history, conversation_id=conversation_id))
        context = self._capturing_provider.last_context

        return SystemTurnResult(
            response_text=result["response"],
            severity=result["severity"],
            reasoning=result["reasoning"],
            graph_context_matched=bool(context and context.matched),
            surfaced_red_flag_indicators=(
                [rf.indicator for rf in context.red_flags] if context else []
            ),
            surfaced_followup_questions=(
                [rf.followup_question for rf in context.red_flags] if context else []
            ),
            cap_reached=result.get("cap_reached", False),
            tokens_used=result.get("tokens_used", 0),
        )
