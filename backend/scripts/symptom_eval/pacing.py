"""Keeps a live eval under a provider's tokens-per-minute limit by spacing the system's turns."""
import time
from typing import Callable

from scripts.symptom_eval.system_under_test import SystemTurnResult, SystemUnderTestPort


class Pacer:
    """Shared by every paced system of a run, so the gap holds across legs and conversations.

    Only the system under test is paced: its turns carry the system prompt and the graph block, so they
    are the bulk of the tokens. Groq's free tier allows 8,000 tokens a minute; at about 1.9k tokens a turn,
    a 20 s gap stays under it.
    """

    def __init__(
        self,
        min_gap_s: float,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._min_gap_s = min_gap_s
        self._clock = clock
        self._sleep = sleep
        self._last_start: float | None = None

    def wait(self) -> None:
        if self._last_start is not None:
            remaining = self._last_start + self._min_gap_s - self._clock()
            if remaining > 0:
                self._sleep(remaining)
        self._last_start = self._clock()


class PacedSystem(SystemUnderTestPort):
    def __init__(self, inner: SystemUnderTestPort, pacer: Pacer) -> None:
        self._inner = inner
        self._pacer = pacer

    def respond(self, patient_message: str, history: list[dict], conversation_id: str) -> SystemTurnResult:
        self._pacer.wait()
        return self._inner.respond(patient_message, history, conversation_id)
