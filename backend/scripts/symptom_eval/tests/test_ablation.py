import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from scripts.symptom_eval.ablation import (
    MAX_CONSECUTIVE_FAILURES, CheckpointStore, TooManyFailures, run_ablation, run_leg,
)
from scripts.symptom_eval.domain import Vignette
from scripts.symptom_eval.system_under_test import SystemTurnResult

VIGNETTES = [
    Vignette("1", "dizzy", [], "emergent", 1),
    Vignette("2", "sore throat", [], "routine", 5),
]


class _FakeSystem:
    def __init__(self, severity):
        self._severity = severity

    def respond(self, patient_message, history, conversation_id=None):
        return SystemTurnResult("classified", self._severity, "why", False)


class _CountingSystem:
    """Tracks how many times respond() actually ran — lets a resume test
    prove skipped vignettes never hit the system again, not just that the
    final counts happen to add up."""

    def __init__(self, severity):
        self._severity = severity
        self.calls: list[str] = []

    def respond(self, patient_message, history, conversation_id=None):
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


class _FlakySystem:
    """Raises on the conversations whose id ends with a listed 'case:repeat'."""

    def __init__(self, fail_on):
        self._fail_on = fail_on

    def respond(self, patient_message, history, conversation_id=None):
        if conversation_id.rsplit(":", 2)[-2:] in [f.split(":") for f in self._fail_on]:
            raise RuntimeError("tool_use_failed")
        return SystemTurnResult("classified", "emergent", "why", False)


def _run_flaky(fail_on, vignettes=VIGNETTES, repeats=1, checkpoint=None, on_failure=None):
    return run_leg(
        "off", vignettes, lambda provider: _FlakySystem(fail_on), _FakeSimulator(), None, None,
        checkpoint=checkpoint, repeats=repeats, on_failure=on_failure,
    )


class TestSkipFailedConversations:
    def test_a_failed_conversation_is_reported_and_left_out_while_the_others_are_recorded(self, tmp_path):
        failures = []
        checkpoint = CheckpointStore(str(tmp_path / "ck.jsonl"))

        leg = _run_flaky(["1:0"], checkpoint=checkpoint, on_failure=lambda cid, err: failures.append((cid, err)))

        assert leg.confusion_matrix["count"] == 1
        assert [cid for cid, _ in failures] == ["original:off:1:0"]
        assert isinstance(failures[0][1], RuntimeError)
        assert not checkpoint.has("original", "off", "1", 0)  # a resume reruns it
        assert checkpoint.has("original", "off", "2", 0)

    def test_without_a_handler_the_first_error_still_stops_the_run(self):
        with pytest.raises(RuntimeError, match="tool_use_failed"):
            _run_flaky(["1:0"])

    def test_the_run_aborts_after_consecutive_failures(self):
        everything = [f"1:{r}" for r in range(MAX_CONSECUTIVE_FAILURES + 2)]
        calls = []

        with pytest.raises(TooManyFailures):
            _run_flaky(everything, vignettes=VIGNETTES[:1], repeats=MAX_CONSECUTIVE_FAILURES + 2,
                       on_failure=lambda cid, err: calls.append(cid))

        assert len(calls) == MAX_CONSECUTIVE_FAILURES

    def test_a_success_resets_the_consecutive_count(self):
        pattern = ["1:0", "1:1", "1:3", "1:4"]  # fail, fail, ok, fail, fail: never 3 in a row

        leg = _run_flaky(pattern, vignettes=VIGNETTES[:1], repeats=5, on_failure=lambda cid, err: None)

        assert leg.confusion_matrix["count"] == 1


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
    def respond(self, patient_message, history, conversation_id=None):
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

    def test_each_repeat_of_each_case_is_its_own_conversation_and_the_cap_flag_reaches_the_checkpoint(self, tmp_path):
        ids: list[str | None] = []

        class _Recording:
            def respond(self, patient_message, history, conversation_id=None):
                ids.append(conversation_id)
                return SystemTurnResult("classified", "urgent", "why", False, cap_reached=True, tokens_used=640)

        checkpoint = CheckpointStore(str(tmp_path / "checkpoint.jsonl"))
        run_leg("static", VIGNETTES[:1], lambda provider: _Recording(), _FakeSimulator(), None, None,
                checkpoint=checkpoint, variant="lay", repeats=2)

        assert ids == ["lay:static:1:0", "lay:static:1:1"]
        entries = checkpoint.entries_for("lay", "static")
        assert [e["transcript"][0]["cap_reached"] for e in entries] == [True, True]
        assert [e["transcript"][0]["tokens_used"] for e in entries] == [640, 640]

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


class TestOptionalJudges:
    def test_no_judges_stores_null_and_scores_severity_only(self, tmp_path):
        path = str(tmp_path / "checkpoint.jsonl")
        result = run_leg(
            "off", VIGNETTES, lambda provider: _FakeSystem("emergent"),
            _FakeSimulator(), None, None, checkpoint=CheckpointStore(path),
        )

        entry = CheckpointStore(path).entries_for("original", "off")[0]
        assert entry["coverage"] is None
        assert entry["gain"] is None
        assert result.confusion_matrix["count"] == 2
        assert result.elicitation_coverage == [None, None]
        assert result.information_gain == [None, None]

    def test_null_scores_survive_reload(self, tmp_path):
        path = str(tmp_path / "checkpoint.jsonl")
        run_leg(
            "off", VIGNETTES, lambda provider: _FakeSystem("emergent"),
            _FakeSimulator(), None, None, checkpoint=CheckpointStore(path),
        )

        rows, coverages, gains = CheckpointStore(path).rows_for("original", "off")
        assert len(rows) == 2
        assert coverages == [None, None]
        assert gains == [None, None]

    def test_one_judge_off_other_on(self, tmp_path):
        path = str(tmp_path / "checkpoint.jsonl")
        result = run_leg(
            "off", VIGNETTES, lambda provider: _FakeSystem("emergent"),
            _FakeSimulator(), None, _FakeRubricJudge(), checkpoint=CheckpointStore(path),
        )

        assert result.elicitation_coverage == [None, None]
        assert all(gain is not None for gain in result.information_gain)


class TestTranscriptPersistence:
    def test_transcript_roundtrips(self, tmp_path):
        path = str(tmp_path / "checkpoint.jsonl")
        _run(path, _FakeSystem("emergent"))

        entry = CheckpointStore(path).entries_for("original", "off")[0]

        assert entry["transcript"] == [{
            "turn_index": 0, "patient_message": "dizzy", "system_response": "classified",
            "graph_context_matched": False, "cap_reached": False, "tokens_used": 0,
            "complaint_name": None, "surfaced_red_flag_indicators": [], "surfaced_followup_questions": [],
        }]

    def test_the_matched_complaint_the_red_flags_and_the_final_reasoning_reach_the_checkpoint(self, tmp_path):
        class _Surfacing:
            def respond(self, patient_message, history, conversation_id=None):
                return SystemTurnResult(
                    "classified", "emergent", "crushing chest pain with shock signs", True,
                    surfaced_red_flag_indicators=["Shock"],
                    surfaced_followup_questions=["Are you feeling faint?"],
                    complaint_name="Chest pain (cardiac features)",
                )

        path = str(tmp_path / "checkpoint.jsonl")
        _run(path, _Surfacing())

        entry = CheckpointStore(path).entries_for("original", "off")[0]
        turn = entry["transcript"][0]

        assert turn["complaint_name"] == "Chest pain (cardiac features)"
        assert turn["surfaced_red_flag_indicators"] == ["Shock"]
        assert turn["surfaced_followup_questions"] == ["Are you feeling faint?"]
        assert entry["final_reasoning"] == "crushing chest pain with shock signs"

    def test_entry_without_transcript_still_loads(self, tmp_path):
        path = tmp_path / "checkpoint.jsonl"
        path.write_text(json.dumps({
            "provider": "off", "case_id": "1",
            "confusion_row": {"case_id": "1", "predicted": "emergent", "gold": "emergent",
                              "correct": True, "under_triaged": False},
            "coverage": None, "gain": None,
        }) + "\n")

        entry = CheckpointStore(str(path)).entries_for("original", "off")[0]

        assert "transcript" not in entry
