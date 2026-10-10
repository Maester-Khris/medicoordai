import json
import os
import logging
from config import llm_provider_chain
from graph.base import GraphContextProvider
from graph.factory import get_graph_provider
from llm.base import BaseLLMClient, LLMMessage
from llm.tools import ALL_TOOLS, TRIAGE_RESPONSE
from llm.prompts import build_system_prompt, build_medical_context_block, build_graph_context_block
from services.proximity import find_nearest_facilities
from services.triage_eval import check_emergency_mismatch, check_facility_groundedness

logger = logging.getLogger(__name__)


KNOWN_PROVIDERS = ("groq", "openai", "anthropic")


def _build_provider_client(provider: str, max_retries: int | None) -> BaseLLMClient:
    """One provider client. Imports are deferred so unused provider packages don't cause ImportError."""
    if provider == "anthropic":
        from llm.anthropic_client import AnthropicClient
        return AnthropicClient(max_retries=max_retries)
    if provider == "openai":
        from llm.openai_client import OpenAIClient
        return OpenAIClient(max_retries=max_retries)
    from llm.groq_client import GroqClient
    return GroqClient(max_retries=max_retries)


def get_llm_client() -> BaseLLMClient:
    """
    Factory. Every provider client comes back wrapped in InstrumentedLLMClient.

    LLM_PROVIDER_CHAIN unset: one client chosen by LLM_PROVIDER (groq by default), with the SDK's
    own retries, exactly as before.
    LLM_PROVIDER_CHAIN="groq,openai,anthropic": those providers in that order behind
    FallbackLLMClient, each with SDK retries off (the next provider is the retry). A name that is
    unknown, or whose key is missing, is skipped with a warning.
    """
    from llm.instrumented import InstrumentedLLMClient

    chain = llm_provider_chain()
    if not chain:
        provider = os.environ.get("LLM_PROVIDER", "groq").lower()
        if provider not in KNOWN_PROVIDERS:
            provider = "groq"
        return InstrumentedLLMClient(_build_provider_client(provider, None), provider)

    from llm.fallback import FallbackLLMClient

    clients: list[BaseLLMClient] = []
    for provider in chain:
        if provider not in KNOWN_PROVIDERS:
            logger.warning("llm_provider_skipped", extra={"provider": provider, "reason": "unknown provider"})
            continue
        try:
            clients.append(InstrumentedLLMClient(_build_provider_client(provider, 0), provider))
        except RuntimeError as exc:  # a missing key or model
            logger.warning("llm_provider_skipped", extra={"provider": provider, "reason": str(exc)})
    if not clients:
        raise RuntimeError("LLM_PROVIDER_CHAIN names no usable provider")
    return FallbackLLMClient(clients)


class LLMAgent:
    """
    Stateless triage agent facade.

    Stateless: caller provides full conversation history on every call.
    Context window: last TRIAGE_CONTEXT_WINDOW messages from cache_chat.

    Two-pass design:
      Pass 1: LLM classifies severity via triage_response tool (no facility knowledge)
      Pass 2: Proximity tool runs in Python (deterministic, from cache)
              LLM generates grounded response with real facility name injected
    """

    def __init__(
        self,
        client: BaseLLMClient | None = None,
        graph_provider: GraphContextProvider | None = None,
    ) -> None:
        self._client = client or get_llm_client()
        self._graph_provider = graph_provider or get_graph_provider()
        self._max_followups = int(os.environ.get("TRIAGE_MAX_FOLLOWUPS", "4"))
        self._min_turns_before_triage = int(os.environ.get("TRIAGE_MIN_TURNS", "3"))
        self._context_window = int(os.environ.get("TRIAGE_CONTEXT_WINDOW", "10"))
        self._temperature = 0.2
        self._response_temperature = 0.3
        self._stop_sequences = ["</response>"]

    def respond(
        self,
        user_message: str,
        history: list[dict],
        lat: float | None = None,
        lng: float | None = None,
        user_profile: dict | None = None,
    ) -> dict:
        """
        Main entry point. Returns:
        {
            "response": str,
            "severity": str | None,
            "reasoning": str | None,
            "recommended_facility": dict | None,
            "nearby_facilities": list[dict],
            "turn_type": "followup" | "triage",
        }
        """
        messages = self._build_messages(user_message, history, user_profile=user_profile)
        user_turns = sum(1 for m in history if m.get("role") == "user")
        force_classify = user_turns >= self._max_followups

        return self._run(
            messages, lat, lng,
            force=force_classify,
            user_turns=user_turns,
        )

    def _build_messages(
        self, user_message: str, history: list[dict],
        user_profile: dict | None = None,
    ) -> list[LLMMessage]:
        system_prompt = build_system_prompt(self._max_followups)
        if user_profile and user_profile.get("medical_chat_opt_in"):
            medical_block = build_medical_context_block(
                allergies=user_profile.get("allergies"),
                conditions=user_profile.get("conditions"),
                blood_type=user_profile.get("blood_type"),
            )
            if medical_block:
                system_prompt += medical_block

        recent = history[-self._context_window:]
        recent_user_msgs = [h["content"] for h in recent if h["role"] == "user"]
        graph_context = self._graph_provider.get_symptom_graph_context(
            user_message, recent_user_msgs
        )
        if graph_context.matched:
            # Design §6: Sprint 19 attributes a follow-up question back to the
            # red flag that triggered it via this log line, not new instrumentation.
            logger.info(
                "graph_context_matched",
                extra={
                    "complaint_name": graph_context.complaint_name,
                    "indicators": [rf.indicator for rf in graph_context.red_flags],
                },
            )
        graph_block = build_graph_context_block(graph_context)
        if graph_block:
            system_prompt += graph_block

        msgs = [
            LLMMessage(role="system", content=system_prompt)
        ]
        for h in recent:
            msgs.append(LLMMessage(role=h["role"], content=h["content"]))
        msgs.append(LLMMessage(role="user", content=user_message))
        return msgs

    def _run(
        self,
        messages: list[LLMMessage],
        lat: float | None,
        lng: float | None,
        force: bool,
        user_turns: int = 0,
    ) -> dict:
        force_tool = TRIAGE_RESPONSE.name if force else None

        resp = self._client.chat(
            messages=messages,
            tools=ALL_TOOLS,
            temperature=self._temperature,
            stop=self._stop_sequences,
            force_tool=force_tool,
        )

        # Tool call list is the authoritative signal — not finish_reason.
        # Groq Llama models may return both text content and tool_calls simultaneously;
        # when tool_calls is non-empty the tool call takes absolute precedence.
        if resp.tool_calls:
            for tool_call in resp.tool_calls:
                if tool_call["name"] == TRIAGE_RESPONSE.name:

                    args = json.loads(tool_call["arguments"])
                    is_emergency = args.get("severity") == "emergent"
                    below_min_turns = user_turns < self._min_turns_before_triage

                    # Emergency and ceiling-force both bypass the minimum turn gate
                    if below_min_turns and not is_emergency and not force:
                        logger.warning(
                            "triage_suppressed_below_min_turns",
                            extra={
                                "user_turns": user_turns,
                                "min_turns": self._min_turns_before_triage,
                                "severity": args.get("severity"),
                            },
                        )
                        return {
                            "response": resp.content or "Could you tell me more about your symptoms?",
                            "severity": None,
                            "reasoning": None,
                            "recommended_facility": None,
                            "nearby_facilities": [],
                            "turn_type": "followup",
                        }

                    return self._handle_triage(tool_call, messages, lat, lng, user_turns)
            logger.warning("unexpected_tool_call")
            return {
                "response": "I need a bit more information. Can you describe your symptoms?",
                "severity": None,
                "reasoning": None,
                "recommended_facility": None,
                "nearby_facilities": [],
                "turn_type": "followup",
            }

        # No tool call — conversational follow-up response
        return {
            "response": resp.content or "Could you tell me more about your symptoms?",
            "severity": None,
            "reasoning": None,
            "recommended_facility": None,
            "nearby_facilities": [],
            "turn_type": "followup",
        }

    def _handle_triage(
        self,
        tool_call: dict,
        messages: list[LLMMessage],
        lat: float | None,
        lng: float | None,
        user_turns: int = 0,
    ) -> dict:
        args = json.loads(tool_call["arguments"])
        severity = args["severity"]
        reasoning = args["reasoning"]
        original_user_message = next(
            (m.content for m in reversed(messages) if m.role == "user"), ""
        )
        if check_emergency_mismatch(original_user_message, severity):
            logger.warning(
                "emergency_mismatch_detected",
                extra={"severity": severity, "user_turns": user_turns},
            )
        logger.info(
            "triage_called",
            extra={
                "severity": severity,
                "information_sufficient": args.get("information_sufficient"),
                "user_turns": user_turns,
            },
        )
        # Location is used whenever coordinates were provided by the client.
        # The LLM does not decide this — the backend knows from the request.
        needs_location = (lat is not None and lng is not None)

        recommended_facility = None
        nearby_facilities: list[dict] = []

        if needs_location:
            facilities = find_nearest_facilities(lat=lat, lng=lng, severity=severity)
            if facilities:
                recommended_facility = facilities[0]
                nearby_facilities = facilities[1:]

        response_text = self._generate_grounded_response(
            messages=messages,
            severity=severity,
            reasoning=reasoning,
            facility=recommended_facility,
        )

        grounding = check_facility_groundedness(response_text, recommended_facility)
        logger.info(
            "triage_grounding_checked",
            extra={
                "severity": severity,
                "facility_provided": recommended_facility is not None,
                "grounded": grounding["grounded"],
                "user_turns": user_turns,
            },
        )

        return {
            "response": response_text,
            "severity": severity,
            "reasoning": reasoning,
            "recommended_facility": recommended_facility,
            "nearby_facilities": nearby_facilities,
            "turn_type": "triage",
        }

    def _generate_grounded_response(
        self,
        messages: list[LLMMessage],
        severity: str,
        reasoning: str,
        facility: dict | None,
    ) -> str:
        if facility:
            facility_fact = (
                f"The nearest appropriate facility is: {facility['name']} "
                f"at {facility['address']}, approximately {facility['distanceKm']} km away. "
                f"Use this exact facility name in your response — do not modify or replace it."
            )
        else:
            facility_fact = (
                "No location data is available. Do not mention any specific facility. "
                "Advise the patient to call 211 or search online for nearby care."
            )

        grounding = LLMMessage(
            role="system",
            content=(
                f"Symptom severity has been classified as: {severity}.\n"
                f"Internal reasoning (do not reveal): {reasoning}\n\n"
                f"{facility_fact}\n\n"
                f"Write a warm, concise response to the patient (2-4 sentences). "
                f"Mention the severity level and the facility name. "
                f"Do not recommend treatments or medications. "
                f"Do not repeat the internal reasoning. "
                f"Do not ask follow-up questions — triage is complete. "
                f"Provide only the recommendation and next steps."
            ),
        )

        resp = self._client.chat(
            messages=messages + [grounding],
            tools=None,
            temperature=self._response_temperature,
        )

        return resp.content or "Please proceed to the recommended facility for assessment."
