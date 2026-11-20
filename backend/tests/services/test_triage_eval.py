# backend/tests/services/test_triage_eval.py
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from services.triage_eval import check_emergency_mismatch


class TestCheckEmergencyMismatch:
    def test_fires_when_emergency_keyword_present_but_severity_is_low(self):
        assert check_emergency_mismatch(["I have chest pain"], "routine") is True

    def test_does_not_fire_when_severity_matches_emergent(self):
        assert check_emergency_mismatch(["I have chest pain"], "emergent") is False

    def test_does_not_fire_without_an_emergency_keyword(self):
        assert check_emergency_mismatch(["I have a mild headache"], "routine") is False
