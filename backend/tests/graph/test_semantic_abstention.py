from graph.semantic.abstention import Decision, anchor_scores, decide
from graph.semantic.candidates import Candidate


def test_accepts_when_both_conditions_hold():
    assert decide({"a": 0.8, "b": 0.6}, threshold=0.5, margin=0.1) == Decision(True, "ok")


def test_rejects_low_top_score():
    assert decide({"a": 0.4, "b": 0.1}, threshold=0.5, margin=0.1) == Decision(False, "low_score")


def test_rejects_when_gap_to_second_is_small():
    assert decide({"a": 0.8, "b": 0.75}, threshold=0.5, margin=0.1) == Decision(False, "small_gap")


def test_single_anchor_needs_only_the_threshold():
    assert decide({"a": 0.5}, threshold=0.5, margin=0.3) == Decision(True, "ok")  # the threshold is inclusive
    assert decide({"a": 0.49}, threshold=0.5, margin=0.3) == Decision(False, "low_score")


def test_empty_scores_are_rejected():
    assert decide({}, threshold=0.0, margin=0.0) == Decision(False, "no_candidates")


def test_anchor_scores_takes_the_max_per_anchor():
    cands = [Candidate("c1", "a", 0.6, "x"), Candidate("c2", "a", 0.9, "y"), Candidate("c3", "b", 0.7, "z")]
    assert anchor_scores(cands) == {"a": 0.9, "b": 0.7}
    assert anchor_scores([]) == {}
