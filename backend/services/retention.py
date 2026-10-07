"""Chat-text retention: triggered when a new guest arrives, at most once per hour."""
import logging

from services import guest_store
from services.wait_times import redis_client

logger = logging.getLogger(__name__)

PURGE_LOCK_KEY = "demo:purge:lock"
PURGE_INTERVAL_SECONDS = 3600


def _purge_is_due() -> bool:
    try:
        return bool(redis_client.set(PURGE_LOCK_KEY, "1", nx=True, ex=PURGE_INTERVAL_SECONDS))
    except Exception:
        return True  # no Redis, no throttle: the delete is idempotent and indexed


def purge_if_due() -> None:
    if not _purge_is_due():
        return
    try:
        deleted = guest_store.purge_expired_sessions()
        logger.info("guest_sessions_purged", extra={"deleted": deleted})
    except Exception as exc:
        logger.warning("guest_purge_failed", extra={"error_type": type(exc).__name__})
