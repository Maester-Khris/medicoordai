import hmac
import logging
import types
from uuid import UUID

from fastapi import Header, HTTPException
from starlette.concurrency import run_in_threadpool
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from config import demo_mode, internal_token
from services import guest_store
from services.auth import verify_token
from services.retention import purge_if_due

logger = logging.getLogger(__name__)


async def get_current_user(authorization: str = Header(...)) -> object:
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing or malformed Authorization header")
    token = authorization.removeprefix("Bearer ").strip()
    return verify_token(token)


def _is_internal(header_value: str) -> bool:
    expected = internal_token()
    return bool(expected) and hmac.compare_digest(header_value.encode(), expected.encode())


async def get_actor(request: Request, authorization: str = Header(default="")) -> object:
    """Who is calling: a guest (DEMO_MODE) or a Supabase user. Exposes .id, .email, .is_guest."""
    if not demo_mode():
        user = await get_current_user(authorization)
        return types.SimpleNamespace(id=user.id, email=user.email, is_guest=False)  # type: ignore[attr-defined]

    try:
        guest_id = str(UUID(request.headers.get("X-Guest-Id", "")))
    except ValueError:
        raise HTTPException(400, "Missing or malformed X-Guest-Id header") from None

    internal = _is_internal(request.headers.get("X-Internal", ""))
    try:
        created = await run_in_threadpool(guest_store.touch_guest, guest_id, internal)
    except Exception as exc:
        logger.error("guest_touch_failed", extra={"error_type": type(exc).__name__})
        raise HTTPException(503, "Database unavailable") from exc
    if created:
        await run_in_threadpool(purge_if_due)

    request.state.guest_id = guest_id
    return types.SimpleNamespace(id=guest_id, email=None, is_guest=True)


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        request.state.user_id = None
        if request.url.path == "/metrics":
            # /metrics authenticates via its own static bearer secret
            # (verify_metrics_token), not a Supabase JWT — running it through
            # verify_token() here would reject it as a malformed token and
            # surface as a 503, before the route's own check ever runs.
            return await call_next(request)
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header.removeprefix("Bearer ").strip()
            try:
                user = verify_token(token)
                request.state.user_id = user.id
            except HTTPException as exc:
                if exc.status_code != 401:
                    # Raising here would escape FastAPI's exception handling:
                    # ExceptionMiddleware sits inside user middleware in the
                    # Starlette stack, so a raise from dispatch() surfaces as
                    # a raw 500 instead of the intended status code.
                    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
                logger.warning(
                    "auth_token_invalid",
                    extra={"path": request.url.path},
                )
        return await call_next(request)
