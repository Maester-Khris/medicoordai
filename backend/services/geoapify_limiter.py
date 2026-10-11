"""
Token bucket rate limiter for external Geoapify Routing API calls.

Protects the shared Geoapify subscription rate limit from being exceeded by this process.
GEOAPIFY_RATE_PER_SECOND sets the token rate and bucket capacity per worker process (the
overall account plan rate divided across running backend processes).

Priority requests (urgent and emergent clinical triage) are never refused because delay
in emergency care routing could harm patients; priority requests borrow tokens into debt
capped at minus capacity, which non-priority routine requests subsequently pay back as the
bucket refills over time. Non-priority requests are granted only when sufficient tokens are
available in full, falling back to straight-line distance estimates when the budget is spent.
"""
import time

import config

# In-process token bucket state.
_tokens: float | None = None
_last_time: float | None = None


def take(count: int, priority: bool, now: float | None = None) -> bool:
    """
    Attempts to draw `count` tokens from the rate limiter bucket.
    Priority calls always succeed (allowing token debt down to -capacity),
    whereas non-priority calls require sufficient positive balance to draw all tokens.
    """
    global _tokens, _last_time

    current_time = time.monotonic() if now is None else now
    capacity = float(config.env_int("GEOAPIFY_RATE_PER_SECOND", 5, minimum=1, maximum=1000))

    if _tokens is None or _last_time is None:
        _tokens = capacity
        _last_time = current_time
    else:
        elapsed = current_time - _last_time
        if elapsed > 0:
            _tokens = min(capacity, _tokens + elapsed * capacity)
            _last_time = current_time

    if priority:
        _tokens = max(-capacity, _tokens - count)
        return True

    if _tokens >= count:
        _tokens -= count
        return True

    return False


def reset_for_tests() -> None:
    """Resets the token bucket state between test runs."""
    global _tokens, _last_time
    _tokens = None
    _last_time = None
