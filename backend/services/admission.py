"""Admission control for chat turns.

Past a limit on chat turns in flight in this process, a new turn is refused at
once with a busy answer instead of being queued. The limit is per process, a
refused turn is answered at once instead of queued, and everything here runs on
the event loop thread between awaits, so it needs no lock.
"""
from collections.abc import Callable, Iterator
import contextlib
import random

import config
import metrics


class Busy(Exception):
    """Raised when the number of chat turns in flight has reached MAX_TURNS_IN_FLIGHT."""


_in_flight: int = 0


def in_flight() -> int:
    return _in_flight


metrics.bind_turns_in_flight(in_flight)


@contextlib.contextmanager
def admit() -> Iterator[None]:
    limit = config.env_int("MAX_TURNS_IN_FLIGHT", 0, minimum=0, maximum=100000)
    global _in_flight
    if limit != 0 and _in_flight >= limit:
        metrics.TURNS_REJECTED.inc()
        raise Busy()
    _in_flight += 1
    try:
        yield
    finally:
        _in_flight -= 1


def retry_after_seconds(rng: Callable[[], float] = random.random) -> int:
    base = config.env_int("ADMISSION_RETRY_SECONDS", 3, minimum=1, maximum=60)
    return base + int(rng() * 3)


def reset_for_tests() -> None:
    global _in_flight
    _in_flight = 0
