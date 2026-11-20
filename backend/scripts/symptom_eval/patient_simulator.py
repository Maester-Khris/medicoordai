"""
PatientSimulatorPort + AnthropicPatientSimulator — plays the vignette's
patient, discloses DisclosureItems only when a system question targets
them. Reuses AnthropicClient (backend/llm/anthropic_client.py) as-is — this
role only needs BaseLLMClient.chat(), no new LLM wrapper (design §5: Claude
is fixed for this role regardless of GRAPH_RAG_PROVIDER/LLM_PROVIDER, so the
simulator is never the same model instance as the system under test).
"""
import os
from abc import ABC, abstractmethod

from llm.anthropic_client import AnthropicClient
from llm.base import BaseLLMClient, LLMMessage
from llm.groq_client import GroqClient
from llm.sync import run_sync
from scripts.symptom_eval.claude_cli_client import ClaudeCliClient
from scripts.symptom_eval.domain import ConversationTurn, Vignette

SIMULATOR_TEMPERATURE = 0.3  # requested; AnthropicClient does not send it (see llm/anthropic_client.py)

SIMULATOR_SYSTEM_PROMPT = """You are role-playing a patient in a triage chat, following a strict script. You will ONLY disclose the facts listed below, and ONLY when the assistant's question actually asks about that fact. Never volunteer a fact that wasn't asked about. Never state a CTAS level, triage category, or diagnosis. Keep every reply to 1-2 short sentences, in first person, as a real patient would speak.

Facts you may disclose (only when asked):
{checklist_text}

If the assistant asks about something not in this list, say you're not sure or give a brief, plausible, non-committal answer consistent with the case — do not invent a new red-flag-worthy fact."""


class PatientSimulatorPort(ABC):
    @abstractmethod
    def reply(
        self, vignette: Vignette, system_question: str, history: list[ConversationTurn]
    ) -> str:
        ...


def _format_checklist(vignette: Vignette) -> str:
    return "\n".join(
        f"- ({item.category}) {item.first_person_phrasing}"
        for item in vignette.disclosure_items
        if not item.disclosed
    )


class AnthropicPatientSimulator(PatientSimulatorPort):
    def __init__(self, client: BaseLLMClient | None = None):
        self._client = client or AnthropicClient()

    @property
    def model_name(self) -> str:
        return self._client.model_name

    def reply(
        self, vignette: Vignette, system_question: str, history: list[ConversationTurn]
    ) -> str:
        system_prompt = SIMULATOR_SYSTEM_PROMPT.format(
            checklist_text=_format_checklist(vignette)
        )
        messages = [LLMMessage(role="system", content=system_prompt)]
        for turn in history:
            messages.append(LLMMessage(role="user", content=turn.system_response))
            messages.append(LLMMessage(role="assistant", content=turn.patient_message))
        messages.append(LLMMessage(role="user", content=system_question))

        resp = run_sync(self._client.chat(messages=messages, tools=None, temperature=SIMULATOR_TEMPERATURE))
        return resp.content or "I'm not sure."


# The default patient on Groq: a different model family from the system under test (gpt-oss-120b),
# so the patient is never the same model answering itself. Measured clean: no reasoning in the reply.
DEFAULT_GROQ_SIMULATOR_MODEL = "qwen/qwen3.8-27b"


def simulator_from_env() -> "AnthropicPatientSimulator":
    """EVAL_SIMULATOR_PROVIDER: anthropic (default, claude-haiku-4-5), groq (EVAL_SIMULATOR_MODEL) or claude-cli (headless `claude -p`).

    The class name is historical: it plays the patient with whatever chat client it is given.
    """
    provider = os.environ.get("EVAL_SIMULATOR_PROVIDER", "anthropic").strip().lower()
    if provider == "anthropic":
        return AnthropicPatientSimulator()
    if provider == "groq":
        model = os.environ.get("EVAL_SIMULATOR_MODEL", DEFAULT_GROQ_SIMULATOR_MODEL)
        system_model = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")
        if model == system_model:
            raise ValueError(f"The simulator and the system under test are the same model ({model}).")
        return AnthropicPatientSimulator(client=GroqClient(model=model))
    if provider == "claude-cli":
        return AnthropicPatientSimulator(client=ClaudeCliClient())
    raise ValueError(f"EVAL_SIMULATOR_PROVIDER must be 'anthropic', 'groq' or 'claude-cli', got {provider!r}")
