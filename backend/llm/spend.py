"""Per-conversation token spend store and capping.

Why fail open:
A broken counter must never block a possible emergency; same rule as rate_limit.py.
If Redis is unreachable or raises an error, the store allows the operation to proceed
without interrupting conversation flow.

Why a 24 h expiry:
A conversation does not outlive a day; keys must not accumulate indefinitely in Redis.

Why Redis:
State is out of process memory since Sprint 22; INCRBY is atomic across replicas,
ensuring consistent counting across multiple server processes.
"""
import logging
from typing import Any, Protocol, runtime_checkable

from starlette.concurrency import run_in_threadpool

from metrics import LLM_SPEND_STORE_ERRORS

logger = logging.getLogger(__name__)

__all__ = [
    "SpendStore",
    "InMemorySpendStore",
    "RedisSpendStore",
    "conversation_cap_reached",
]


@runtime_checkable
class SpendStore(Protocol):
    """Per-conversation token spend tracking interface."""

    async def total(self, conversation_id: str) -> int:
        ...

    async def add(self, conversation_id: str, tokens: int) -> None:
        ...


class InMemorySpendStore:
    """In-memory spend store for tests and eval harness."""

    def __init__(self) -> None:
        self._spend: dict[str, int] = {}

    async def total(self, conversation_id: str) -> int:
        return self._spend.get(conversation_id, 0)

    async def add(self, conversation_id: str, tokens: int) -> None:
        if tokens <= 0:
            return
        self._spend[conversation_id] = self._spend.get(conversation_id, 0) + tokens


class RedisSpendStore:
    """Redis-backed spend store using atomic increments and a TTL."""

    def __init__(self, client: Any, ttl_seconds: int = 86400) -> None:
        self._client = client
        self._ttl_seconds = ttl_seconds

    async def total(self, conversation_id: str) -> int:
        key = f"llm_spend:{conversation_id}"
        try:
            value = await run_in_threadpool(self._client.get, key)
            if value is None:
                return 0
            return int(value)
        except Exception as exc:
            logger.warning("spend_store_total_failed", extra={"error_type": type(exc).__name__})
            LLM_SPEND_STORE_ERRORS.inc()
            return 0

    async def add(self, conversation_id: str, tokens: int) -> None:
        if tokens <= 0:
            return
        key = f"llm_spend:{conversation_id}"
        try:
            pipe = self._client.pipeline()
            pipe.incrby(key, tokens)
            pipe.expire(key, self._ttl_seconds)  # same round trip: a key can never exist without its expiry
            await run_in_threadpool(pipe.execute)
        except Exception as exc:
            logger.warning("spend_store_add_failed", extra={"error_type": type(exc).__name__})
            LLM_SPEND_STORE_ERRORS.inc()


def conversation_cap_reached(spent: int, cap: int) -> bool:
    """Check whether conversation spend has reached or exceeded token cap."""
    return spent >= cap
