"""Guest demo endpoints: public /config, and guest-only /feedback and /events."""
from fastapi import APIRouter, Depends, HTTPException, Response
from starlette.concurrency import run_in_threadpool

from config import DOWNTOWN_TORONTO, demo_mode, modes_enabled, starter_prompts
from middleware.auth import get_actor
from models import AppConfig, FeedbackRequest, GuestEventRequest
from services import guest_store

router = APIRouter(tags=["demo"])


def _guest_id(actor: object) -> str:
    if not getattr(actor, "is_guest", False):
        raise HTTPException(404, "Not available")
    return str(actor.id)  # type: ignore[attr-defined]


@router.get("/config")
def get_config() -> AppConfig:
    on = demo_mode()
    return AppConfig(
        demo_mode=on,
        starter_prompts=starter_prompts(),
        downtown_fallback=DOWNTOWN_TORONTO,
        modes_enabled=modes_enabled(),
    )


@router.post("/feedback", status_code=204)
async def post_feedback(body: FeedbackRequest, actor: object = Depends(get_actor)) -> Response:
    guest_id = _guest_id(actor)
    comment = (body.comment or "").strip() or None
    stored = await run_in_threadpool(
        guest_store.upsert_feedback, guest_id, str(body.session_id), str(body.message_id), body.thumb, comment
    )
    if not stored:
        raise HTTPException(404, "Message not found")
    return Response(status_code=204)


@router.post("/events", status_code=204)
async def post_event(body: GuestEventRequest, actor: object = Depends(get_actor)) -> Response:
    guest_id = _guest_id(actor)
    recorded = await run_in_threadpool(
        guest_store.record_event, guest_id, body.type, str(body.session_id), body.mode, body.duration_ms
    )
    if not recorded:
        raise HTTPException(404, "Session not found")
    return Response(status_code=204)
