import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from services import geoapify_limiter


@pytest.fixture(autouse=True)
def _clean(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GEOAPIFY_RATE_PER_SECOND", "5")
    geoapify_limiter.reset_for_tests()
    yield
    geoapify_limiter.reset_for_tests()


def test_it_starts_full_and_refuses_when_empty() -> None:
    assert geoapify_limiter.take(3, priority=False, now=0.0)
    assert geoapify_limiter.take(2, priority=False, now=0.0)
    assert not geoapify_limiter.take(1, priority=False, now=0.0)


def test_a_request_larger_than_what_is_left_is_refused_whole() -> None:
    assert geoapify_limiter.take(4, priority=False, now=0.0)
    assert not geoapify_limiter.take(2, priority=False, now=0.0)
    assert geoapify_limiter.take(1, priority=False, now=0.0)


def test_it_refills_at_the_rate_and_never_above_it() -> None:
    assert geoapify_limiter.take(5, priority=False, now=0.0)
    assert not geoapify_limiter.take(1, priority=False, now=0.1)
    assert geoapify_limiter.take(1, priority=False, now=0.3)   # 0.3 s at 5 per second is 1.5 tokens
    assert geoapify_limiter.take(5, priority=False, now=100.0)
    assert not geoapify_limiter.take(1, priority=False, now=100.0)


def test_priority_is_never_refused_and_is_paid_back_by_the_others() -> None:
    assert geoapify_limiter.take(5, priority=False, now=0.0)
    assert geoapify_limiter.take(3, priority=True, now=0.0)
    assert not geoapify_limiter.take(1, priority=False, now=0.5)  # 2.5 refilled, still below zero
    assert geoapify_limiter.take(1, priority=False, now=1.0)


def test_the_debt_of_priority_requests_is_bounded() -> None:
    for _ in range(100):
        assert geoapify_limiter.take(3, priority=True, now=0.0)
    assert geoapify_limiter.take(1, priority=False, now=2.5)  # at most one second of debt
