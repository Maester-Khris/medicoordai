import json
import os
import logging
from dataclasses import dataclass, field
from config import (
    llm_breaker_cooldown_seconds,
    llm_breaker_failures,
    llm_conversation_token_cap,
    llm_provider_chain,
    emergency_mismatch_mode,
    groundedness_guard_mode,
    llm_retry_attempts,
    red_flag_floor_mode,
)
from graph.base import GraphContextProvider
from graph.factory import get_graph_provider
from llm.base import BaseLLMClient, LLMMessage, LLMResponse
from llm.spend import SpendStore, conversation_cap_reached
from llm.tools import ALL_TOOLS, TRIAGE_RESPONSE

VALID_SEVERITIES = frozenset(TRIAGE_RESPONSE.parameters["severity"]["enum"])  # routine | moderate | urgent | emergent
from metrics import LLM_CAP_REACHED
from llm.prompts import build_system_prompt, build_medical_context_block, build_graph_context_block
from services import facility_load
from services.proximity import find_nearest_facilities
from services.red_flags import RedFlag, find_red_flags
from services.recommendation import rank_facilities
from services.triage_eval import check_emergency_mismatch, check_facility_groundedness, reply_problem
from starlette.concurrency import run_in_threadpool

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


def build_guarded_client(provider: str, *, breaker: bool) -> BaseLLMClient:
    """One provider behind the whole guard stack, outermost first:
    Instrumented -> CircuitBreaker (optional) -> Retrying -> the provider client.

    The SDK's own retries are off (max_retries=0) so llm.retry is the only retry policy: a 400 is
    never retried and the eval sees the same behaviour as production. The breaker sits outside the
    retries, so one exhausted retry sequence counts as one failure and an open breaker skips them.
    The eval builds its client here too (breaker=False, see scripts/symptom_eval/system_under_test.py).
    """
    from llm.breaker import CircuitBreakerLLMClient
    from llm.instrumented import InstrumentedLLMClient
    from llm.retry import RetryingLLMClient, shared_retry_budget

    client: BaseLLMClient = RetryingLLMClient(
        _build_provider_client(provider, 0), provider=provider, attempts=llm_retry_attempts(),
        budget=shared_retry_budget(),
    )
    if breaker:
        client = CircuitBreakerLLMClient(
            client, provider=provider, failure_threshold=llm_breaker_failures(),
            cooldown_seconds=llm_breaker_cooldown_seconds(),
        )
    return InstrumentedLLMClient(client, provider)


def get_llm_client() -> BaseLLMClient:
    """
    Factory. Every provider comes back behind build_guarded_client (retry, breaker, metrics).

    LLM_PROVIDER_CHAIN unset: one client chosen by LLM_PROVIDER (groq by default).
    LLM_PROVIDER_CHAIN="groq,openai,anthropic": those providers in that order behind
    FallbackLLMClient. A name that is unknown, or whose key is missing, is skipped with a warning.
    """
    chain = llm_provider_chain()
    if not chain:
        provider = os.environ.get("LLM_PROVIDER", "groq").lower()
        if provider not in KNOWN_PROVIDERS:
            provider = "groq"
        return build_guarded_client(provider, breaker=True)

    from llm.fallback import FallbackLLMClient

    clients: list[BaseLLMClient] = []
    for provider in chain:
        if provider not in KNOWN_PROVIDERS:
            logger.warning("llm_provider_skipped", extra={"provider": provider, "reason": "unknown provider"})
            continue
        try:
            clients.append(build_guarded_client(provider, breaker=True))
        except RuntimeError as exc:  # a missing key or model
            logger.warning("llm_provider_skipped", extra={"provider": provider, "reason": str(exc)})
    if not clients:
        raise RuntimeError("LLM_PROVIDER_CHAIN names no usable provider")
    return FallbackLLMClient(clients)


CLASSIFY_TEMPERATURE = 0.2
RESPONSE_TEMPERATURE = 0.3


def triage_max_followups() -> int:
    return int(os.environ.get("TRIAGE_MAX_FOLLOWUPS", "4"))


def triage_min_turns() -> int:
    return int(os.environ.get("TRIAGE_MIN_TURNS", "3"))


def triage_context_window() -> int:
    return int(os.environ.get("TRIAGE_CONTEXT_WINDOW", "10"))


# Fixed wording, not model output: the eval must be reproducible, so the run manifest records the
# hash of these strings. Edit them freely, but a changed hash starts a new eval configuration.
SAFETY_LINE = "If this is an emergency, call 911. For other health help, call 211."
CAPPED_NOTE = (
    "I'm wrapping up here to keep this conversation short, so this is based on what you've shared "
    "so far. If your symptoms change or get worse, call 911."
)
CAPPED_NO_RESULT = f"I couldn't finish assessing this. {SAFETY_LINE}"
EMERGENT_OPENER = "Please call 911 now."


def capped_reply(severity: str, facility: dict | None) -> str:
    """The patient-facing text once a conversation has spent its token allowance.

    No model call: the cap exists to stop spend, so the grounded reply that normally costs a
    second call is a template. Everything it says comes from the classification and the facility
    the backend already chose.
    """
    if facility:
        where = (
            f"The nearest appropriate facility is {facility['name']} at {facility['address']}, "
            f"about {facility['distanceKm']} km away."
        )
    else:
        where = "I can't point to a facility from here, so please call 211 or search online for nearby care."
    urgency = f" {EMERGENT_OPENER}" if severity == "emergent" else ""
    return f"Based on what you've told me, this looks {severity}.{urgency} {where} {CAPPED_NOTE}"


def ensure_911_first(text: str, severity: str) -> str:
    """The rule for an emergent reply: it says 911, and 911 comes before any 211. A reply that
    already follows the rule is returned as it is; otherwise the fixed opener goes in front.
    Other severities are never touched."""
    if severity != "emergent":
        return text
    if "911" in text and ("211" not in text or text.index("911") < text.index("211")):
        return text
    return f"{EMERGENT_OPENER} {text}"


def facility_fact(facility: dict | None, severity: str) -> str:
    """The sentence that tells the model which facility to name (or that there is none)."""
    if facility:
        return (
            f"The nearest appropriate facility is: {facility['name']} "
            f"at {facility['address']}, approximately {facility['distanceKm']} km away. "
            f"Use this exact facility name in your response — do not modify or replace it."
        )
    if severity == "emergent":
        return (
            "No location data is available. Do not mention any specific facility. "
            "Tell the patient to call 911 now. Do not suggest any other phone number."
        )
    return (
        "No location data is available. Do not mention any specific facility. "
        "Advise the patient to call 211 or search online for nearby care."
    )


def escalate(severity: str, flagged: bool) -> str:
    """The floor's whole rule: a red flag can only raise a severity to emergent, never lower one."""
    return "emergent" if flagged else severity


def capped_reply_fingerprint() -> str:
    """Every fixed string and template a capped turn can show, rendered. The eval manifest hashes it,
    so changing any wording starts a new configuration instead of silently mixing two."""
    sample_facility = {"name": "Sample Hospital", "address": "1 Sample St", "distanceKm": 1.0}
    return "\n".join([
        SAFETY_LINE, CAPPED_NOTE, CAPPED_NO_RESULT, EMERGENT_OPENER,
        facility_fact(None, "emergent"), facility_fact(None, "moderate"), facility_fact(sample_facility, "urgent"),
        capped_reply("urgent", sample_facility), capped_reply("emergent", None), capped_reply("emergent", sample_facility),
    ])


@dataclass
class _TurnContext:
    """What one turn needs to know about its conversation's spend, and what it has spent so far.

    One instance per turn, never shared: `tokens_used` is added to by every model call of the turn.
    """

    conversation_id: str | None
    capped: bool
    tokens_used: int = field(default=0)
    user_texts: list[str] = field(default_factory=list)  # every message the patient has sent, current last


def _followup(text: str, ctx: _TurnContext) -> dict:
    """A turn that asks for more information. Past the cap there is nothing left to ask with."""
    return {
        "response": CAPPED_NO_RESULT if ctx.capped else text,
        "severity": None,
        "reasoning": None,
        "recommended_facility": None,
        "nearby_facilities": [],
        "turn_type": "followup",
        "cap_reached": ctx.capped,
        "tokens_used": ctx.tokens_used,
    }


class LLMAgent:
    """
    Stateless triage agent facade.

    Stateless: caller provides full conversation history on every call.
    Context window: last TRIAGE_CONTEXT_WINDOW messages (caller reads history from the store).

    Two-pass design:
      Pass 1: LLM classifies severity via triage_response tool (no facility knowledge)
      Pass 2: Proximity tool runs in Python (deterministic, from cache)
              LLM generates grounded response with real facility name injected
    """

    def __init__(
        self,
        client: BaseLLMClient | None = None,
        graph_provider: GraphContextProvider | None = None,
        spend_store: SpendStore | None = None,
    ) -> None:
        self._client = client or get_llm_client()
        self._graph_provider = graph_provider or get_graph_provider()
        self._spend_store = spend_store  # None: no cap (callers that have no conversation to count)
        self._max_followups = triage_max_followups()
        self._min_turns_before_triage = triage_min_turns()
        self._context_window = triage_context_window()
        self._temperature = CLASSIFY_TEMPERATURE
        self._response_temperature = RESPONSE_TEMPERATURE
        self._stop_sequences = ["</response>"]

    async def respond(
        self,
        user_message: str,
        history: list[dict],
        lat: float | None = None,
        lng: float | None = None,
        user_profile: dict | None = None,
        conversation_id: str | None = None,
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
            "cap_reached": bool,
            "tokens_used": int,  # prompt + completion tokens of this turn's model calls
        }

        With a `conversation_id` (and a spend store) every model call's tokens are counted against
        that conversation. Once the total reaches LLM_CONVERSATION_TOKEN_CAP the turn is forced to
        classify and answers from a template: the guest still gets a result, with no further spend.
        """
        messages = await run_in_threadpool(
            self._build_messages, user_message, history, user_profile=user_profile
        )
        user_turns = sum(1 for m in history if m.get("role") == "user")
        ctx = await self._turn_context(conversation_id)
        force_classify = user_turns >= self._max_followups or ctx.capped

        # The red-flag floor reads everything the patient has said, not only this message.
        ctx.user_texts = [m["content"] for m in history if m.get("role") == "user"] + [user_message]
        floor_mode = red_flag_floor_mode()
        flags = find_red_flags(ctx.user_texts) if floor_mode != "off" else []
        if flags and floor_mode == "enforce":
            return await self._floor_triage(flags, messages, lat, lng, user_turns, ctx)

        result = await self._run(
            messages, lat, lng,
            force=force_classify,
            user_turns=user_turns,
            ctx=ctx,
        )
        if flags:  # shadow: say what the floor would have done, change nothing
            model_severity = result["severity"]
            logger.warning(
                "red_flag_floor_shadow",
                extra={
                    "categories": [flag.category for flag in flags],
                    "model_severity": model_severity,
                    "would_escalate": escalate(model_severity or "routine", True) != model_severity,
                    "user_turns": user_turns,
                },
            )
        return result

    async def _floor_triage(
        self, flags: list[RedFlag], messages: list[LLMMessage], lat: float | None, lng: float | None,
        user_turns: int, ctx: _TurnContext,
    ) -> dict:
        """The floor's answer: emergent, decided in code. The classification call is skipped, so an
        emergency costs one model call (the reply) instead of two. Only category ids are logged."""
        categories = [flag.category for flag in flags]
        logger.warning("red_flag_floor_applied", extra={"categories": categories, "user_turns": user_turns})
        tool_call = {
            "id": "red-flag-floor",
            "name": TRIAGE_RESPONSE.name,
            "arguments": json.dumps({
                "severity": "emergent",
                "reasoning": f"red-flag floor: {categories[0]}",
                "information_sufficient": True,
            }),
        }
        return await self._handle_triage(tool_call, messages, lat, lng, user_turns, ctx)

    async def _turn_context(self, conversation_id: str | None) -> _TurnContext:
        if conversation_id is None or self._spend_store is None:
            return _TurnContext(conversation_id=None, capped=False)
        spent = await self._spend_store.total(conversation_id)
        capped = conversation_cap_reached(spent, llm_conversation_token_cap())
        if capped:
            LLM_CAP_REACHED.inc()
            logger.warning("conversation_cap_reached", extra={"spent_tokens": spent})
        return _TurnContext(conversation_id=conversation_id, capped=capped)

    async def _chat(self, ctx: _TurnContext, **call: object) -> LLMResponse:
        """The one place a model call is made and its tokens are counted."""
        resp = await self._client.chat(**call)
        usage = resp.usage or {}
        tokens = (usage.get("prompt_tokens") or 0) + (usage.get("completion_tokens") or 0)
        ctx.tokens_used += tokens
        if ctx.conversation_id is not None and self._spend_store is not None:
            await self._spend_store.add(ctx.conversation_id, tokens)
        return resp

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

    async def _run(
        self,
        messages: list[LLMMessage],
        lat: float | None,
        lng: float | None,
        force: bool,
        user_turns: int = 0,
        ctx: _TurnContext | None = None,
    ) -> dict:
        ctx = ctx or _TurnContext(conversation_id=None, capped=False)
        force_tool = TRIAGE_RESPONSE.name if force else None

        resp = await self._chat(
            ctx,
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
                    if args.get("severity") not in VALID_SEVERITIES:
                        # The model's output is untrusted: the tool enum is only a hint to it. Fail toward
                        # the safe side so a synonym or injected value never delays care or drops the 911 line.
                        logger.warning("triage_invalid_severity", extra={"user_turns": user_turns})
                        args["severity"] = "emergent"
                        tool_call = {**tool_call, "arguments": json.dumps(args)}
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
                        return _followup(resp.content or "Could you tell me more about your symptoms?", ctx)

                    return await self._handle_triage(tool_call, messages, lat, lng, user_turns, ctx)
            logger.warning("unexpected_tool_call")
            return _followup("I need a bit more information. Can you describe your symptoms?", ctx)

        # No tool call — conversational follow-up response
        return _followup(resp.content or "Could you tell me more about your symptoms?", ctx)

    async def _handle_triage(
        self,
        tool_call: dict,
        messages: list[LLMMessage],
        lat: float | None,
        lng: float | None,
        user_turns: int = 0,
        ctx: _TurnContext | None = None,
    ) -> dict:
        ctx = ctx or _TurnContext(conversation_id=None, capped=False)
        args = json.loads(tool_call["arguments"])
        severity = args["severity"]
        reasoning = args["reasoning"]
        original_user_message = next(
            (m.content for m in reversed(messages) if m.role == "user"), ""
        )
        escalated_by_mismatch = False
        mismatch_mode = emergency_mismatch_mode()
        user_texts = ctx.user_texts or [original_user_message]
        if mismatch_mode != "off" and check_emergency_mismatch(user_texts, severity):
            logger.warning(
                "emergency_mismatch_detected",
                extra={
                    "severity": severity,
                    "categories": [flag.category for flag in find_red_flags(user_texts)],
                    "guard_mode": mismatch_mode,
                    "user_turns": user_turns,
                },
            )
            if mismatch_mode == "enforce":
                # The model under-called an emergency the patient described. Raise it, and answer
                # from the template: the reply the model would write was for the wrong severity.
                severity = escalate(severity, True)
                reasoning = f"{reasoning}; red-flag mismatch"
                escalated_by_mismatch = True
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
                ranked = rank_facilities(facilities, severity, lat, lng)
                recommended_facility = ranked[0]
                nearby_facilities = ranked[1:]
                facility_load.record(recommended_facility, severity, lat, lng)

        if ctx.capped or escalated_by_mismatch:
            response_text = capped_reply(severity, recommended_facility)
        else:
            response_text = await self._generate_grounded_response(
                messages=messages,
                severity=severity,
                reasoning=reasoning,
                facility=recommended_facility,
                ctx=ctx,
            )

        # The model decides whether to say 911 (measured: it left it out in 5 of 10 emergent replies,
        # and with no location sent the guest to 211). For an emergency the number is not optional
        # and comes before any 211.
        response_text = ensure_911_first(response_text, severity)

        # A reply that is forged, not prose or does not name the chosen facility never reaches the
        # patient in enforce mode: the template says the same thing from what the backend decided.
        guard_mode = groundedness_guard_mode()
        problem = reply_problem(response_text, recommended_facility) if guard_mode != "off" else None
        grounding = check_facility_groundedness(response_text, recommended_facility)
        logger.info(
            "triage_grounding_checked",
            extra={
                "severity": severity,
                "facility_provided": recommended_facility is not None,
                "grounded": grounding["grounded"],
                "problem": problem,
                "guard_mode": guard_mode,
                "user_turns": user_turns,
            },
        )
        if problem and guard_mode == "enforce":
            logger.warning("reply_replaced_by_template", extra={"problem": problem, "severity": severity})
            response_text = capped_reply(severity, recommended_facility)

        return {
            "response": response_text,
            "severity": severity,
            "reasoning": reasoning,
            "recommended_facility": recommended_facility,
            "nearby_facilities": nearby_facilities,
            "turn_type": "triage",
            "cap_reached": ctx.capped,
            "tokens_used": ctx.tokens_used,
        }

    async def _generate_grounded_response(
        self,
        messages: list[LLMMessage],
        severity: str,
        reasoning: str,
        facility: dict | None,
        ctx: _TurnContext,
    ) -> str:
        grounding = LLMMessage(
            role="system",
            content=(
                f"Symptom severity has been classified as: {severity}.\n"
                f"Internal reasoning (do not reveal): {reasoning}\n\n"
                f"{facility_fact(facility, severity)}\n\n"
                f"Write a warm, concise response to the patient (2-4 sentences). "
                f"Mention the severity level and the facility name. "
                f"Do not recommend treatments or medications. "
                f"Do not repeat the internal reasoning. "
                f"Do not ask follow-up questions — triage is complete. "
                f"Provide only the recommendation and next steps."
            ),
        )

        resp = await self._chat(
            ctx,
            messages=messages + [grounding],
            tools=None,
            temperature=self._response_temperature,
        )

        return resp.content or "Please proceed to the recommended facility for assessment."


_agent: LLMAgent | None = None


def get_agent() -> LLMAgent:
    """Return the process-wide LLMAgent instance, building it on first use.

    Reused because the agent keeps no conversation state and its provider clients
    hold the HTTP connection pools.
    """
    global _agent
    if _agent is None:
        from llm.spend import RedisSpendStore
        from services.wait_times import redis_client  # imported here: it needs UPSTASH_REDIS_URL at import

        _agent = LLMAgent(spend_store=RedisSpendStore(redis_client))
    return _agent
