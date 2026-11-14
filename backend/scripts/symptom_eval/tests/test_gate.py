import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

import pytest

from scripts.symptom_eval.gate import build_baseline, evaluate_gate, gate_command


def _row(case_id, predicted, gold, provider="off", repeat=0, variant="lay"):
    return {
        "variant": variant, "provider": provider, "case_id": case_id, "repeat": repeat,
        "confusion_row": {"case_id": case_id, "predicted": predicted, "gold": gold,
                          "correct": predicted == gold, "under_triaged": False},
    }


SENTINELS = [("1", "emergent"), ("2", "emergent"), ("8", "moderate")]
WATCH = [("6", "urgent")]


def _history(repeats=3):
    rows = []
    for r in range(repeats):
        rows += [_row("1", "emergent", "emergent", repeat=r), _row("2", "emergent", "emergent", repeat=r),
                 _row("8", "moderate", "moderate", repeat=r), _row("6", "moderate", "urgent", repeat=r),
                 _row("1", "urgent", "emergent", provider="static", repeat=r)]  # another leg: ignored
    return rows


def _baseline():
    return build_baseline(_history(), sentinel_ids=["1", "2", "8"], watch_ids=["6"], variant="lay", sources=["x.jsonl"])


class TestBuildBaseline:
    def test_a_sentinel_records_its_gold_expected_answer_and_stability(self):
        baseline = _baseline()

        by_id = {s["case_id"]: s for s in baseline["sentinels"]}
        assert by_id["1"] == {"case_id": "1", "gold": "emergent", "expected": "emergent", "stability": "3/3"}
        assert baseline["watch"][0]["observed"] == {"moderate": 3}

    def test_only_the_off_leg_counts(self):
        rows = _history() + [_row("2", "routine", "emergent", provider="neo4j_semantic")]

        baseline = build_baseline(rows, ["1", "2", "8"], ["6"], "lay", ["x"])

        assert {s["case_id"]: s["stability"] for s in baseline["sentinels"]}["2"] == "3/3"

    def test_a_case_that_is_not_stable_and_correct_cannot_be_a_sentinel(self):
        rows = _history() + [_row("8", "urgent", "moderate", repeat=3)]

        with pytest.raises(ValueError, match="8"):
            build_baseline(rows, ["1", "2", "8"], ["6"], "lay", ["x"])

    def test_a_case_with_no_runs_cannot_be_a_sentinel(self):
        with pytest.raises(ValueError, match="99"):
            build_baseline(_history(), ["99"], [], "lay", ["x"])


class TestEvaluateGate:
    def test_a_run_that_matches_the_baseline_passes(self):
        rows = [_row("1", "emergent", "emergent"), _row("2", "emergent", "emergent"), _row("8", "moderate", "moderate")]

        result = evaluate_gate(rows, _baseline())

        assert result.passed and result.reasons == []

    def test_an_emergent_sentinel_answered_lower_fails_alone(self):
        rows = [_row("1", "urgent", "emergent"), _row("2", "emergent", "emergent"), _row("8", "moderate", "moderate")]

        result = evaluate_gate(rows, _baseline())

        assert not result.passed
        assert any("under-triaged" in r and "1" in r for r in result.reasons)

    def test_one_flip_on_a_non_emergent_sentinel_is_tolerated_two_are_not(self):
        base = _baseline()
        one = [_row("1", "emergent", "emergent"), _row("2", "emergent", "emergent"), _row("8", "urgent", "moderate")]
        # two flips: make a second sentinel differ without being a safety miss (emergent stays emergent)
        base_two = build_baseline(
            _history() + [_row("11", "emergent", "emergent", repeat=r) for r in range(3)] +
            [_row("12", "moderate", "moderate", repeat=r) for r in range(3)],
            ["1", "2", "8", "12"], ["6"], "lay", ["x"])
        two = [_row("1", "emergent", "emergent"), _row("2", "emergent", "emergent"),
               _row("8", "urgent", "moderate"), _row("12", "routine", "moderate")]

        assert evaluate_gate(one, base).passed
        failed = evaluate_gate(two, base_two)
        assert not failed.passed and any("differ" in r for r in failed.reasons)

    def test_a_missing_or_unclassified_sentinel_fails(self):
        base = _baseline()
        missing = [_row("1", "emergent", "emergent"), _row("2", "emergent", "emergent")]
        unclassified = [_row("1", "emergent", "emergent"), _row("2", None, "emergent"), _row("8", "moderate", "moderate")]

        assert any("missing" in r for r in evaluate_gate(missing, base).reasons)
        assert any("unclassified" in r for r in evaluate_gate(unclassified, base).reasons)

    def test_watch_cases_are_reported_and_never_fail_the_gate(self):
        rows = [_row("1", "emergent", "emergent"), _row("2", "emergent", "emergent"),
                _row("8", "moderate", "moderate"), _row("6", "routine", "urgent")]

        result = evaluate_gate(rows, _baseline())

        assert result.passed
        assert result.watch == [{"case_id": "6", "gold": "urgent", "baseline": {"moderate": 3}, "now": ["routine"]}]

    def test_other_variants_and_legs_are_ignored(self):
        rows = [_row("1", "emergent", "emergent"), _row("2", "emergent", "emergent"), _row("8", "moderate", "moderate"),
                _row("1", "routine", "emergent", variant="original"),
                _row("2", "routine", "emergent", provider="static")]

        assert evaluate_gate(rows, _baseline()).passed


class TestGateCommand:
    def _write(self, tmp_path, rows):
        checkpoint = tmp_path / "checkpoint.jsonl"
        checkpoint.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
        baseline = tmp_path / "baseline.json"
        baseline.write_text(json.dumps(_baseline()))
        return str(checkpoint), str(baseline)

    def test_exit_code_zero_on_pass_and_one_on_failure(self, tmp_path, capsys):
        good = [_row("1", "emergent", "emergent"), _row("2", "emergent", "emergent"), _row("8", "moderate", "moderate")]
        bad = [_row("1", "urgent", "emergent"), _row("2", "emergent", "emergent"), _row("8", "moderate", "moderate")]

        assert gate_command(*self._write(tmp_path, good)) == 0
        assert gate_command(*self._write(tmp_path, bad)) == 1
        assert "FAIL" in capsys.readouterr().out
