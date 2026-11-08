import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from scripts.symptom_eval.ablation import CheckpointStore, run_ablation, run_leg
from scripts.symptom_eval.domain import Vignette
from scripts.symptom_eval.system_under_test import SystemTurnResult

VIGNETTES = [
    Vignette("1", "dizzy", [], "emergent", 1),
    Vignette("2", "sore throat", [], "routine", 5),
]


class _FakeSystem:
    def __init__(self, severity):
        self._severity = severity

    def respond(self, patient_message, history):
        return SystemTurnResult("classified", self._severity, "why", False)


class _CountingSystem:
    """Tracks how many times respond() actually ran — lets a resume test
    prove skipped vignettes never hit the system again, not just that the
    final counts happen to add up."""

    def __init__(self, severity):
        self._severity = severity
        self.calls: list[str] = []

    def respond(self, patient_message, history):
        self.calls.append(patient_message)
        return SystemTurnResult("classified", self._severity, "why", False)


class _FakeSimulator:
    def reply(self, vignette, system_question, history):
        return "more info"


class _FakeFeatureJudge:
    def was_surfaced(self, feature, transcript_text):
        return False


class _FakeRubricJudge:
    def score_candidates(self, transcript_text):
        return {"routine": 0.25, "moderate": 0.25, "urgent": 0.25, "emergent": 0.25}


class TestRunAblation:
    def test_runs_one_leg_per_provider(self):
        legs = run_ablation(
            vignettes=VIGNETTES,
            system_factory=lambda provider: _FakeSystem(severity="emergent"),
            simulator=_FakeSimulator(),
            feature_judge=_FakeFeatureJudge(),
            rubric_judge=_FakeRubricJudge(),
            providers=("off", "neo4j"),
        )

        assert [leg.provider for leg in legs] == ["off", "neo4j"]
        for leg in legs:
            assert leg.confusion_matrix["count"] == 2
            assert len(leg.elicitation_coverage) == 2
            assert len(leg.information_gain) == 2


class TestCheckpointStore:
    def test_persists_and_reloads_completed_vignette_legs(self, tmp_path):
        path = str(tmp_path / "checkpoint.jsonl")
        checkpoint = CheckpointStore(path)

        run_leg(
            "off", VIGNETTES, lambda provider: _FakeSystem(severity="emergent"),
            _FakeSimulator(), _FakeFeatureJudge(), _FakeRubricJudge(),
            checkpoint=checkpoint,
        )

        reloaded = CheckpointStore(path)
        assert reloaded.has("original", "off", "1", 0)
        assert reloaded.has("original", "off", "2", 0)
        assert reloaded.has("original", "neo4j", "1", 0) is False

        rows, coverages, gains = reloaded.rows_for("original", "off")
        assert [r.case_id for r in rows] == ["1", "2"]
        assert len(coverages) == 2
        assert len(gains) == 2

    def test_resume_skips_already_completed_vignettes(self, tmp_path):
        path = str(tmp_path / "checkpoint.jsonl")
        counting_system = _CountingSystem(severity="emergent")

        first_pass = CheckpointStore(path)
        run_leg(
            "off", [VIGNETTES[0]], lambda provider: counting_system,
            _FakeSimulator(), _FakeFeatureJudge(), _FakeRubricJudge(),
            checkpoint=first_pass,
        )
        assert len(counting_system.calls) == 1  # only case "1" ran

        resumed = CheckpointStore(path)  # simulates a fresh process after a crash
        result = run_leg(
            "off", VIGNETTES, lambda provider: counting_system,
            _FakeSimulator(), _FakeFeatureJudge(), _FakeRubricJudge(),
            checkpoint=resumed,
        )

        assert len(counting_system.calls) == 2  # case "1" skipped, only case "2" ran
        assert result.confusion_matrix["count"] == 2  # but both are in the final result


class _MatchedSystem:
    def respond(self, patient_message, history):
        return SystemTurnResult("classified", "emergent", "why", True)


def _run(path, system, repeats=1, variant="original", vignettes=VIGNETTES):
    return run_leg(
        "off", vignettes, lambda provider: system,
        _FakeSimulator(), _FakeFeatureJudge(), _FakeRubricJudge(),
        checkpoint=CheckpointStore(path), variant=variant, repeats=repeats,
    )


class TestCheckpointKey:
    def test_old_format_line_loads_as_original_repeat_zero(self, tmp_path):
        path = tmp_path / "checkpoint.jsonl"
        old_entry = {
            "provider": "off", "case_id": "1",
            "confusion_row": {"case_id": "1", "predicted": "emergent", "gold": "emergent",
                              "correct": True, "under_triaged": False},
            "coverage": {"case_id": "1", "total_features": 0, "surfaced_count": 0,
                         "elicited_count": 0, "coverage": 0.0, "fraction": 0.0},
            "gain": {"case_id": "1", "entropy_per_turn": [], "gains": []},
        }
        path.write_text(json.dumps(old_entry) + "\n")

        assert CheckpointStore(str(path)).has("original", "off", "1", 0)

    def test_variants_do_not_skip_each_other(self, tmp_path):
        path = str(tmp_path / "checkpoint.jsonl")
        _run(path, _FakeSystem("emergent"), variant="original")

        reloaded = CheckpointStore(path)
        assert reloaded.has("original", "off", "1", 0)
        assert reloaded.has("lay", "off", "1", 0) is False

    def test_resume_skips_only_matching_repeat(self, tmp_path):
        path = str(tmp_path / "checkpoint.jsonl")
        first = _CountingSystem("emergent")
        _run(path, first, repeats=1)
        assert len(first.calls) == 2  # two vignettes, repeat 0 only

        resumed = _CountingSystem("emergent")
        _run(path, resumed, repeats=2)
        assert len(resumed.calls) == 2  # repeat 1 of both vignettes; repeat 0 skipped

        again = _CountingSystem("emergent")
        _run(path, again, repeats=2)
        assert again.calls == []

    def test_graph_context_matched_roundtrips(self, tmp_path):
        path = str(tmp_path / "checkpoint.jsonl")
        _run(path, _MatchedSystem())

        entry = CheckpointStore(path).entries_for("original", "off")[0]
        assert entry["graph_context_matched"] == [True]

    def test_truncated_line_raises_with_line_number(self, tmp_path):
        path = tmp_path / "checkpoint.jsonl"
        path.write_text('{"provider": "off", "case_id": "1", "repeat": 0}\n{"provider": "off"\n')

        with pytest.raises(ValueError, match="line 2"):
            CheckpointStore(str(path))
