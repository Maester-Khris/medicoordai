import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from scripts.symptom_eval.pacing import Pacer, PacedSystem


class _Inner:
    def __init__(self):
        self.calls = 0

    def respond(self, patient_message, history, conversation_id):
        self.calls += 1
        return f"reply {self.calls}"


class _Clock:
    def __init__(self):
        self.now = 100.0
        self.slept = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds


class TestPacedSystem:
    def test_the_first_call_does_not_wait_and_the_next_waits_out_the_gap(self):
        clock = _Clock()
        system = PacedSystem(_Inner(), Pacer(20, clock=clock.monotonic, sleep=clock.sleep))

        system.respond("a", [], "c1")
        clock.now += 5  # the call and the caller took 5 s
        system.respond("b", [], "c1")

        assert clock.slept == [15]

    def test_a_gap_that_has_already_passed_is_not_waited_again(self):
        clock = _Clock()
        system = PacedSystem(_Inner(), Pacer(20, clock=clock.monotonic, sleep=clock.sleep))

        system.respond("a", [], "c1")
        clock.now += 30
        system.respond("b", [], "c1")

        assert clock.slept == []

    def test_the_inner_result_is_returned_unchanged(self):
        clock = _Clock()
        inner = _Inner()
        system = PacedSystem(inner, Pacer(1, clock=clock.monotonic, sleep=clock.sleep))

        assert system.respond("a", [], "c1") == "reply 1"
        assert inner.calls == 1


    def test_two_systems_sharing_a_pacer_are_spaced_against_each_other(self):
        clock = _Clock()
        pacer = Pacer(20, clock=clock.monotonic, sleep=clock.sleep)
        first, second = PacedSystem(_Inner(), pacer), PacedSystem(_Inner(), pacer)

        first.respond("a", [], "c1")
        second.respond("b", [], "c2")

        assert clock.slept == [20]
