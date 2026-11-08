"""
Deterministic stand-ins for the system under test and the patient simulator,
so the whole harness (load -> run -> checkpoint -> manifest -> compare) can be
exercised with zero provider calls. The severities are a hash of the leg and
the opening message: stable between runs, different between legs, and
meaningless as results — dry-run output must never be read as a measurement.
"""
import hashlib

from scripts.symptom_eval.domain import SEVERITY_RANK
from scripts.symptom_eval.system_under_test import SystemTurnResult

SEVERITIES = tuple(SEVERITY_RANK)


class FakeSystem:
    def __init__(self, provider: str):
        self._provider = provider

    def respond(self, patient_message: str, history: list[dict]) -> SystemTurnResult:
        opening = history[0]["content"] if history else patient_message
        digest = int(hashlib.sha1(f"{self._provider}|{opening}".encode()).hexdigest(), 16)
        return SystemTurnResult(
            response_text="DRY RUN classification",
            severity=SEVERITIES[digest % len(SEVERITIES)],
            reasoning="dry run",
            graph_context_matched=digest % 2 == 0,
        )


class FakeSimulator:
    def reply(self, vignette, system_question, history) -> str:
        return "dry run reply"
