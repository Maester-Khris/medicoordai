"""Fixed-window rate limit for the demo: chat (LLM quota) and routes (Geoapify quota), one bucket each.

Per guest and per IP, in Redis. The IP is hashed before it becomes a key and the key lives one
window; it is never written to Postgres or to logs. If Redis is unreachable the limiter allows
the request: a broken limiter must not take the demo down.
"""
import hashlib
import logging
import time

import sentry_sdk
from fastapi.responses import JSONResponse
from starlette.requests import Request

from services.wait_times import redis_client

logger = logging.getLogger(__name__)

WINDOW_SECONDS = 600
GUEST_LIMIT = 10
IP_LIMIT = 30
# One conversation can change travel mode several times, so routes get six times the chat allowance.
ROUTES_GUEST_LIMIT = 60
ROUTES_IP_LIMIT = 180
LLM_BUSY_RETRY_SECONDS = 60


def client_ip(request: Request) -> str:
    real_ip = request.headers.get("x-real-ip", "").strip()
    if real_ip:
        return real_ip
    forwarded = [part.strip() for part in request.headers.get("x-forwarded-for", "").split(",") if part.strip()]
    if forwarded:
        return forwarded[-1]  # right-most: appended by our proxy, not typed by the client
    return request.client.host if request.client else "unknown"


def check_rate_limit(
    guest_id: str,
    ip: str,
    now: float | None = None,
    *,
    bucket: str = "chat",
    guest_limit: int = GUEST_LIMIT,
    ip_limit: int = IP_LIMIT,
) -> int | None:
    """Counts this request in `bucket`. Returns seconds until the window ends when over a limit, else None."""
    now = time.time() if now is None else now
    window = int(now // WINDOW_SECONDS)
    ip_hash = hashlib.sha256(ip.encode()).hexdigest()[:32]
    limits = [
        (f"rl:{bucket}:guest:{guest_id}:{window}", guest_limit),
        (f"rl:{bucket}:ip:{ip_hash}:{window}", ip_limit),
    ]
    try:
        pipe = redis_client.pipeline()
        for key, _ in limits:
            pipe.incr(key)
            pipe.expire(key, WINDOW_SECONDS)
        counts = pipe.execute()[0::2]
    except Exception as exc:
        logger.warning("rate_limit_unavailable", extra={"error_type": type(exc).__name__})
        sentry_sdk.capture_message("rate limiter unavailable, allowing requests", level="warning")
        return None

    if any(count > limit for count, (_, limit) in zip(counts, limits)):
        return WINDOW_SECONDS - int(now % WINDOW_SECONDS)
    return None


def busy_response(retry_after: int) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={"code": "busy", "retry_after": retry_after},
        headers={"Retry-After": str(retry_after)},
    )
