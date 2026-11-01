import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import MagicMock, patch

import pytest

from services import rate_limit


class FakeRedis:
    """INCR/EXPIRE through a pipeline, enough for the limiter."""

    def __init__(self) -> None:
        self.counts: dict[str, int] = {}
        self.ttls: dict[str, int] = {}

    def pipeline(self) -> "FakeRedis":
        self._queued: list = []
        return self

    def incr(self, key: str) -> None:
        self._queued.append(("incr", key))

    def expire(self, key: str, seconds: int) -> None:
        self._queued.append(("expire", key, seconds))

    def execute(self) -> list:
        out: list = []
        for op in self._queued:
            if op[0] == "incr":
                self.counts[op[1]] = self.counts.get(op[1], 0) + 1
                out.append(self.counts[op[1]])
            else:
                self.ttls[op[1]] = op[2]
                out.append(True)
        return out


@pytest.fixture()
def fake_redis():
    fake = FakeRedis()
    with patch.object(rate_limit, "redis_client", fake):
        yield fake


def test_tenth_message_passes_eleventh_is_limited(fake_redis) -> None:
    for _ in range(10):
        assert rate_limit.check_rate_limit("g1", "1.1.1.1", now=1000.0) is None
    assert rate_limit.check_rate_limit("g1", "1.1.1.1", now=1000.0) == 200  # 600 - (1000 % 600)


def test_ip_limit_spans_guests(fake_redis) -> None:
    for i in range(30):
        assert rate_limit.check_rate_limit(f"g{i}", "9.9.9.9", now=0.0) is None
    assert rate_limit.check_rate_limit("fresh-guest", "9.9.9.9", now=0.0) == 600


def test_new_window_resets_the_count(fake_redis) -> None:
    for _ in range(11):
        rate_limit.check_rate_limit("g1", "1.1.1.1", now=10.0)
    assert rate_limit.check_rate_limit("g1", "1.1.1.1", now=610.0) is None


def test_raw_ip_never_reaches_redis_and_keys_expire(fake_redis) -> None:
    rate_limit.check_rate_limit("g1", "203.0.113.7", now=0.0)
    assert not any("203.0.113.7" in key for key in fake_redis.counts)
    assert set(fake_redis.ttls.values()) == {rate_limit.WINDOW_SECONDS}


def test_rate_limit_fails_open() -> None:
    broken = MagicMock()
    broken.pipeline.side_effect = ConnectionError("redis down")
    with patch.object(rate_limit, "redis_client", broken), \
         patch.object(rate_limit.sentry_sdk, "capture_message") as capture:
        assert rate_limit.check_rate_limit("g1", "1.1.1.1") is None
    capture.assert_called_once()


def _request(headers: dict[str, str], host: str | None = "10.0.0.1") -> MagicMock:
    request = MagicMock()
    request.headers = headers
    request.client = MagicMock(host=host) if host else None
    return request


def test_client_ip_prefers_x_real_ip_then_rightmost_forwarded() -> None:
    assert rate_limit.client_ip(_request({"x-real-ip": "5.5.5.5", "x-forwarded-for": "1.1.1.1"})) == "5.5.5.5"
    # the left-most entry is whatever the client typed; the proxy appends the real one
    assert rate_limit.client_ip(_request({"x-forwarded-for": "6.6.6.6, 7.7.7.7"})) == "7.7.7.7"
    assert rate_limit.client_ip(_request({})) == "10.0.0.1"
    assert rate_limit.client_ip(_request({}, host=None)) == "unknown"


def test_busy_response_shape() -> None:
    resp = rate_limit.busy_response(120)
    assert resp.status_code == 429 and resp.headers["retry-after"] == "120"
    assert json.loads(resp.body) == {"code": "busy", "retry_after": 120}

def test_buckets_do_not_share_counters(fake_redis) -> None:
    for _ in range(10):
        assert rate_limit.check_rate_limit("g1", "1.1.1.1", now=0.0) is None
    assert rate_limit.check_rate_limit("g1", "1.1.1.1", now=0.0) == 600  # chat bucket is full
    assert rate_limit.check_rate_limit(
        "g1", "1.1.1.1", now=0.0,
        bucket="routes", guest_limit=rate_limit.ROUTES_GUEST_LIMIT, ip_limit=rate_limit.ROUTES_IP_LIMIT,
    ) is None


def test_routes_bucket_uses_its_own_limits(fake_redis) -> None:
    def call() -> int | None:
        return rate_limit.check_rate_limit(
            "g1", "2.2.2.2", now=0.0,
            bucket="routes", guest_limit=rate_limit.ROUTES_GUEST_LIMIT, ip_limit=rate_limit.ROUTES_IP_LIMIT,
        )

    assert rate_limit.ROUTES_GUEST_LIMIT == 60 and rate_limit.ROUTES_IP_LIMIT == 180
    for _ in range(60):
        assert call() is None
    assert call() == 600


def test_keys_are_namespaced_by_bucket(fake_redis) -> None:
    rate_limit.check_rate_limit("g1", "3.3.3.3", now=0.0)
    rate_limit.check_rate_limit("g1", "3.3.3.3", now=0.0, bucket="routes")
    assert any(key.startswith("rl:chat:guest:g1:") for key in fake_redis.counts)
    assert any(key.startswith("rl:routes:guest:g1:") for key in fake_redis.counts)


def test_limits_default_to_the_constants(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("RATE_LIMIT_CHAT_GUEST", "RATE_LIMIT_CHAT_IP", "RATE_LIMIT_ROUTES_GUEST", "RATE_LIMIT_ROUTES_IP"):
        monkeypatch.delenv(name, raising=False)
    assert rate_limit.limits_for("chat") == (10, 30)
    assert rate_limit.limits_for("routes") == (60, 180)


def test_limits_can_be_raised_from_the_environment(fake_redis, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RATE_LIMIT_CHAT_GUEST", "3")
    monkeypatch.setenv("RATE_LIMIT_CHAT_IP", "1000")
    assert rate_limit.limits_for("chat") == (3, 1000)
    for _ in range(3):
        assert rate_limit.check_rate_limit("g1", "4.4.4.4", now=0.0) is None
    assert rate_limit.check_rate_limit("g1", "4.4.4.4", now=0.0) == 600


def test_an_invalid_limit_keeps_the_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RATE_LIMIT_ROUTES_GUEST", "lots")
    monkeypatch.setenv("RATE_LIMIT_ROUTES_IP", "0")
    assert rate_limit.limits_for("routes") == (60, 180)


def test_explicit_limits_win_over_the_environment(fake_redis, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RATE_LIMIT_CHAT_GUEST", "1000")
    assert rate_limit.check_rate_limit("g1", "5.5.5.5", now=0.0, guest_limit=1, ip_limit=50) is None
    assert rate_limit.check_rate_limit("g1", "5.5.5.5", now=0.0, guest_limit=1, ip_limit=50) == 600


def test_an_unknown_bucket_uses_the_chat_limits() -> None:
    assert rate_limit.limits_for("something-else") == rate_limit.limits_for("chat")
