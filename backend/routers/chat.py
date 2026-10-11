import hashlib
import json
import logging
from datetime import datetime, date

from fastapi import APIRouter, Depends, Request, Header, BackgroundTasks, HTTPException
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

import config
from middleware.auth import get_actor
from services import admission, guest_store
from services.rate_limit import LLM_BUSY_RETRY_SECONDS, busy_response, check_rate_limit, client_ip
from models import CreateSessionRequest, SendMessageRequest
from services.chat import (
    generate_session_title, create_session, add_message,
    get_past_conversations, get_older_messages, get_recent_messages,
)
from services.llm_agent import get_agent
from services.geoapify_shadow import should_sample, log_routing_comparison


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

    sessions, messages = await run_in_threadpool(get_past_conversations, user_id)
    payload = {"sessions": sessions, "messages": messages}
    ser_payload = _ser(payload)
    serialized = json.dumps(ser_payload, sort_keys=True)
    etag = f'"{hashlib.sha256(serialized.encode()).hexdigest()[:32]}"'

    if if_none_match == etag:
        return Response(status_code=304)

    return JSONResponse(
        content=ser_payload,
        headers={"ETag": etag, "Cache-Control": "no-cache"},
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

    # Blocking database call: keep it off the event loop.
    session = await run_in_threadpool(create_session, user_id=user_id, title=title)
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


async def _run_turn(
    body: SendMessageRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    current_user: object,
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

    # Answering without the earlier messages is worse than failing: triage requires context.
    limit = config.env_int("CHAT_HISTORY_MESSAGES", 20, minimum=1, maximum=200)
    try:
        history = await run_in_threadpool(get_recent_messages, session_id, user_id, limit)
    except Exception as exc:
        logger.error(
            "history_read_failed",
            extra={"request_id": request_id, "session_id": session_id, "error_type": type(exc).__name__},
        )
        raise HTTPException(503, "Conversation unavailable") from exc

    # The store calls hit the database and run in the thread pool. The agent awaits the
    # LLM on the event loop, so no thread is held for the seconds an LLM call takes.
    try:
        user_msg = await run_in_threadpool(
            add_message, session_id=session_id, user_id=user_id, role="user", content=body.content
        )
    except guest_store.SessionNotFound:
        raise HTTPException(404, "Session not found") from None

    try:
        user_profile: dict | None = None
        if not _is_guest(current_user):
            try:
                from db import supabase_select
                user_profile = await run_in_threadpool(
                    supabase_select,
                    "profile",
                    params={"user_id": f"eq.{user_id}", "select": "allergies,conditions,blood_type,medical_chat_opt_in"},
                    single=True,
                )  # type: ignore[assignment]
            except Exception as exc:
                logger.warning("profile_fetch_failed", extra={"request_id": request_id, "error": str(exc)})

        result = await get_agent().respond(
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

    assistant_msg = await run_in_threadpool(
        add_message, session_id=session_id, user_id=user_id, role="assistant", content=result["response"]
    )

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


@router.post("/message", response_model=None)
async def send_message(
    body: SendMessageRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    current_user: object = Depends(get_actor),
) -> Response | dict:
    """The check comes before the rate limit and before any write, so a refused turn stores nothing and does not use the guest's allowance."""
    try:
        with admission.admit():
            return await _run_turn(body, request, background_tasks, current_user)
    except admission.Busy:
        return busy_response(admission.retry_after_seconds())


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
    messages = await run_in_threadpool(
        get_older_messages, session_id=session_id, before_id=before_id, user_id=user_id
    )

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
    current_user: object = Depends(get_actor),
) -> dict:
    """No-op endpoint kept for backward compatibility with web app logout; does nothing."""
    return {"status": "cache cleared"}

