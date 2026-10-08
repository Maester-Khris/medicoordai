import logging
from datetime import datetime, date

from fastapi import APIRouter, Depends, Request, Header, BackgroundTasks
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from fastapi import HTTPException

from middleware.auth import get_actor
from services import guest_store
from services.rate_limit import LLM_BUSY_RETRY_SECONDS, busy_response, check_rate_limit, client_ip
from models import CreateSessionRequest, SendMessageRequest
from services.chat import (
    generate_session_title, create_session, add_message,
    get_past_conversations, get_older_messages,
)
from services.geoapify_shadow import should_sample, log_routing_comparison
from cache_chat import (
    get_user_cache, set_user_cache,
    append_message_to_cache, append_session_to_cache,
    invalidate_user_cache,
)


def _ser(obj: object) -> object:
    """Recursively convert datetime objects to ISO strings for JSONResponse."""
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: _ser(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_ser(item) for item in obj]
    return obj

router = APIRouter(prefix="/chat", tags=["chat"])
logger = logging.getLogger(__name__)


def _trunc_uid(uid: str) -> str:
    return uid[:8] + "..."


def _is_guest(actor: object) -> bool:
    return bool(getattr(actor, "is_guest", False))


async def _record_guest_event(actor: object, event_type: str, session_id: str) -> None:
    """Best-effort: an event that cannot be written never fails the request."""
    if not _is_guest(actor):
        return
    try:
        await run_in_threadpool(guest_store.record_event, str(actor.id), event_type, session_id)  # type: ignore[attr-defined]
    except Exception as exc:
        logger.warning("guest_event_failed", extra={"event_type": event_type, "error_type": type(exc).__name__})


@router.get("/sessions")
async def past_conversations(
    if_none_match: str = Header(default=""),
    current_user: object = Depends(get_actor),
) -> Response:
    """
    Returns the 5 most recent sessions with their 20 latest messages each.
    Supports ETag conditional requests — returns 304 if data unchanged.
    """
    user_id = str(current_user.id)  # type: ignore[attr-defined]

    cached, cached_etag = get_user_cache(user_id)

    if cached is None:
        sessions, messages = get_past_conversations(user_id)
        cached_etag = set_user_cache(user_id, sessions, messages)
        cached = {"sessions": sessions, "messages": messages}
        logger.info(
            "chat cache miss — fetched from Supabase",
            extra={"user_id": _trunc_uid(user_id), "session_count": len(sessions)},
        )
    else:
        logger.info("chat cache hit", extra={"user_id": _trunc_uid(user_id)})

    if if_none_match == cached_etag:
        return Response(status_code=304)

    return JSONResponse(
        content=_ser(cached),
        headers={"ETag": cached_etag, "Cache-Control": "no-cache"},
    )


@router.post("/sessions")
async def create_new_session(
    body: CreateSessionRequest,
    request: Request,
    current_user: object = Depends(get_actor),
) -> dict:
    """Creates a new chat session. Title is derived from the first message."""
    user_id = str(current_user.id)  # type: ignore[attr-defined]
    title = generate_session_title(body.first_message)

    session = create_session(user_id=user_id, title=title)
    append_session_to_cache(user_id, session)
    await _record_guest_event(current_user, "session_started", str(session["id"]))

    logger.info(
        "session created",
        extra={
            "request_id": getattr(request.state, "request_id", None),
            "user_id": _trunc_uid(user_id),
            "session_id": session["id"],
        },
    )
    return _ser(session)


@router.post("/message", response_model=None)
async def send_message(
    body: SendMessageRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    current_user: object = Depends(get_actor),
) -> Response | dict:
    """
    Saves a user message, runs the LLM triage agent, saves the assistant response.
    Returns user message, assistant message, and triage result (null on follow-up turns).
    """
    user_id = str(current_user.id)  # type: ignore[attr-defined]
    session_id = str(body.session_id)
    request_id = getattr(request.state, "request_id", None)

    if _is_guest(current_user):
        retry_after = await run_in_threadpool(check_rate_limit, user_id, client_ip(request))
        if retry_after is not None:
            return busy_response(retry_after)

    # Fetch history from cache for context window
    cache_entry, _ = get_user_cache(user_id)
    history: list[dict] = []
    if cache_entry:
        history = cache_entry.get("messages", {}).get(session_id, [])

    try:
        user_msg = add_message(session_id=session_id, user_id=user_id, role="user", content=body.content)
    except guest_store.SessionNotFound:
        raise HTTPException(404, "Session not found") from None

    append_message_to_cache(user_id, session_id, user_msg)

    try:
        from services.llm_agent import LLMAgent
        from db import supabase_select
        agent = LLMAgent()

        user_profile: dict | None = None
        if not _is_guest(current_user):
            try:
                user_profile = await run_in_threadpool(
                    supabase_select,
                    "profile",
                    params={"user_id": f"eq.{user_id}", "select": "allergies,conditions,blood_type,medical_chat_opt_in"},
                    single=True,
                )  # type: ignore[assignment]
            except Exception as exc:
                logger.warning("profile_fetch_failed", extra={"request_id": request_id, "error": str(exc)})

        result = agent.respond(
            user_message=body.content,
            history=history,
            lat=body.lat,
            lng=body.lng,
            user_profile=user_profile,
        )
    except Exception as exc:
        if getattr(exc, "status_code", None) == 429:  # provider quota: Groq and Anthropic both expose status_code
            logger.warning("llm_quota_exhausted", extra={"request_id": request_id})
            return busy_response(LLM_BUSY_RETRY_SECONDS)
        import sentry_sdk
        sentry_sdk.capture_exception(exc)
        logger.error("llm_agent_failed", extra={"request_id": request_id, "error": str(exc)})
        result = {
            "response": (
                "I'm having trouble processing your request right now. "
                "If this is an emergency, please call 911."
            ),
            "severity": None,
            "reasoning": None,
            "recommended_facility": None,
            "nearby_facilities": [],
            "turn_type": "followup",
        }

    assistant_msg = add_message(
        session_id=session_id, user_id=user_id, role="assistant", content=result["response"]
    )
    append_message_to_cache(user_id, session_id, assistant_msg)

    logger.info(
        "triage_agent_responded",
        extra={
            "request_id": request_id,
            "turn_type": result["turn_type"],
            "severity": result.get("severity"),
            "has_facility": result.get("recommended_facility") is not None,
            "nearby_count": len(result.get("nearby_facilities", [])),
        },
    )

    triage = None
    if result["turn_type"] == "triage":
        triage = {
            "severity": result["severity"],
            "reasoning": result["reasoning"],
            "recommended_facility": result["recommended_facility"],
            "nearby_facilities": result["nearby_facilities"],
        }

    if triage and triage["recommended_facility"]:
        await _record_guest_event(current_user, "recommendation_shown", session_id)

    if (
        triage
        and triage["recommended_facility"]
        and should_sample()
    ):
        background_tasks.add_task(
            log_routing_comparison, body.lat, body.lng, triage["recommended_facility"],
        )

    return _ser({"user_message": user_msg, "assistant_message": assistant_msg, "triage": triage})


@router.get("/sessions/{session_id}/messages")
async def load_older_messages(
    session_id: str,
    before_id: str,
    request: Request,
    current_user: object = Depends(get_actor),
) -> dict:
    """
    Cursor-based pagination — returns messages older than `before_id`.
    Always hits Supabase; older messages are not cached.
    """
    user_id = str(current_user.id)  # type: ignore[attr-defined]
    messages = get_older_messages(session_id=session_id, before_id=before_id, user_id=user_id)

    cached, _ = get_user_cache(user_id)
    if cached:
        existing = cached["messages"].get(session_id, [])
        cached["messages"][session_id] = messages + existing

    logger.info(
        "older messages loaded",
        extra={
            "request_id": getattr(request.state, "request_id", None),
            "user_id": _trunc_uid(user_id),
            "session_id": session_id,
            "count": len(messages),
        },
    )
    return _ser({"messages": messages})


@router.post("/sessions/invalidate")
async def invalidate_cache(
    request: Request,
    current_user: object = Depends(get_actor),
) -> dict:
    """Clears the server-side chat cache for the user — call on logout."""
    user_id = str(current_user.id)  # type: ignore[attr-defined]
    invalidate_user_cache(user_id)
    logger.info(
        "chat cache invalidated",
        extra={"request_id": getattr(request.state, "request_id", None), "user_id": _trunc_uid(user_id)},
    )
    return {"status": "cache cleared"}
