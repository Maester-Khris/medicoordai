import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

import pytest

from llm.spend import InMemorySpendStore, RedisSpendStore, conversation_cap_reached
from observability import _registry


def test_an_unknown_conversation_has_spent_nothing_and_spend_accumulates_per_conversation() -> None:
    async def scenario() -> tuple[int, int, int]:
        store = InMemorySpendStore()
        empty = await store.total("a")
        await store.add("a", 100)
        await store.add("a", 50)
        await store.add("b", 7)
        return empty, await store.total("a"), await store.total("b")

    assert asyncio.run(scenario()) == (0, 150, 7)


class _FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, int] = {}
        self.expiries: dict[str, int] = {}

    def incrby(self, key: str, amount: int) -> int:
        self.values[key] = self.values.get(key, 0) + amount
        return self.values[key]

    def expire(self, key: str, seconds: int) -> bool:
        self.expiries[key] = seconds
        return True

    def get(self, key: str) -> str | None:
        value = self.values.get(key)
        return None if value is None else str(value)  # decode_responses=True returns strings


class _BrokenRedis:
    def incrby(self, key: str, amount: int) -> int:
        raise ConnectionError("down")

    def expire(self, key: str, seconds: int) -> bool:
        raise ConnectionError("down")

    def get(self, key: str) -> str | None:
        raise ConnectionError("down")


def test_redis_store_increments_a_namespaced_key_and_sets_the_expiry() -> None:
    redis_client = _FakeRedis()
    store = RedisSpendStore(redis_client, ttl_seconds=3600)

    async def scenario() -> tuple[int, int]:
        await store.add("session-1", 120)
        await store.add("session-1", 30)
        return await store.total("session-1"), await store.total("session-2")

    assert asyncio.run(scenario()) == (150, 0)
    assert redis_client.values == {"llm_spend:session-1": 150}
    assert redis_client.expiries == {"llm_spend:session-1": 3600}


def test_redis_store_ignores_a_zero_or_negative_amount() -> None:
    redis_client = _FakeRedis()
    asyncio.run(RedisSpendStore(redis_client).add("session-1", 0))
    asyncio.run(RedisSpendStore(redis_client).add("session-1", -5))
    assert redis_client.values == {}


def _store_errors() -> float:
    return _registry.get_sample_value("llm_spend_store_errors_total") or 0.0


def test_a_broken_redis_fails_open_and_is_counted() -> None:
    store = RedisSpendStore(_BrokenRedis())
    before = _store_errors()
    assert asyncio.run(store.total("session-1")) == 0
    asyncio.run(store.add("session-1", 100))  # must not raise
    assert _store_errors() == before + 2


@pytest.mark.parametrize("spent,cap,expected", [(0, 30000, False), (29999, 30000, False),
                                                (30000, 30000, True), (45000, 30000, True)])
def test_conversation_cap_reached(spent: int, cap: int, expected: bool) -> None:
    assert conversation_cap_reached(spent, cap) is expected
