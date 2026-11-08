import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from llm.prompts import build_system_prompt
from scripts.symptom_eval import cli
from scripts.symptom_eval.ablation import AblationLegResult, CheckpointStore
from scripts.symptom_eval.confusion_matrix import ConfusionMatrixRow
from scripts.symptom_eval.patient_simulator import SIMULATOR_SYSTEM_PROMPT, SIMULATOR_TEMPERATURE
from scripts.symptom_eval.run_manifest import ManifestMismatch, manifest_path, sha256_text
from scripts.symptom_eval.system_under_test import SystemTurnResult
from services.llm_agent import CLASSIFY_TEMPERATURE, RESPONSE_TEMPERATURE, triage_max_followups


class _FakeSimulator:
    def reply(self, vignette, system_question, history):
        return "more info"


class _ManifestWatchingSystem:
    """Records whether the manifest already existed when the first turn ran."""

    def __init__(self, checkpoint_path):
        self._checkpoint_path = checkpoint_path
        self.manifest_existed_at_first_call = None

    def respond(self, patient_message, history):
        if self.manifest_existed_at_first_call is None:
            self.manifest_existed_at_first_call = os.path.exists(manifest_path(self._checkpoint_path))
        return SystemTurnResult("classified", "emergent", "why", False)


def _dependencies(system):
    return cli.RunDependencies(
        system_factory=lambda provider: system, simulator=_FakeSimulator(),
        system_model="fake-system-model", simulator_model="fake-simulator-model",
    )


def _run(tmp_path, system, **overrides):
    options = dict(
        limit=1, checkpoint_path=str(tmp_path / "checkpoint.jsonl"), providers=("off",),
        variant="original", repeats=1, judges=False, results_dir=str(tmp_path),
        dependencies=_dependencies(system),
    )
    options.update(overrides)
    return cli.run_ablation_command(**options)


def test_build_judges_disabled_returns_none_without_constructing(monkeypatch):
    def explode(*args, **kwargs):
        raise AssertionError("judge constructed although judges are off")

    monkeypatch.setattr(cli, "DeepEvalFeaturePresenceJudge", explode)
    monkeypatch.setattr(cli, "DeepEvalRubricJudge", explode)

    assert cli.build_judges(False) == (None, None)


def test_build_judges_enabled_constructs_both(monkeypatch):
    monkeypatch.setattr(cli, "DeepEvalFeaturePresenceJudge", lambda: "feature")
    monkeypatch.setattr(cli, "DeepEvalRubricJudge", lambda: "rubric")

    assert cli.build_judges(True) == ("feature", "rubric")


def test_results_writer_handles_null_scores():
    leg = AblationLegResult("off", {"count": 1}, [None], [None])

    serialized = cli.serialize_leg(leg)

    assert json.loads(json.dumps(serialized))["elicitation_coverage"] == [None]
    assert serialized["information_gain"] == [None]


def test_manifest_written_before_first_system_call(tmp_path):
    system = _ManifestWatchingSystem(str(tmp_path / "checkpoint.jsonl"))

    _run(tmp_path, system)

    assert system.manifest_existed_at_first_call is True


def test_no_judges_run_stores_null_scores_in_checkpoint(tmp_path):
    _run(tmp_path, _ManifestWatchingSystem(str(tmp_path / "checkpoint.jsonl")))

    entry = CheckpointStore(str(tmp_path / "checkpoint.jsonl")).entries_for("original", "off")[0]
    assert entry["coverage"] is None and entry["gain"] is None


def test_resume_with_a_different_repeat_count_stops(tmp_path):
    system = _ManifestWatchingSystem(str(tmp_path / "checkpoint.jsonl"))
    _run(tmp_path, system, repeats=1)

    with pytest.raises(ManifestMismatch, match="repeats"):
        _run(tmp_path, system, repeats=2)


def test_lay_variant_run_uses_lay_checklists_and_keys_the_checkpoint(tmp_path):
    _run(tmp_path, _ManifestWatchingSystem(str(tmp_path / "checkpoint.jsonl")), variant="lay")

    checkpoint = CheckpointStore(str(tmp_path / "checkpoint.jsonl"))
    assert checkpoint.entries_for("lay", "off")
    assert checkpoint.entries_for("original", "off") == []


def test_manifest_records_live_prompt_and_temperature_values():
    manifest = cli.build_manifest(
        system_model="m1", simulator_model="m2", providers=("off",), variant="original",
        repeats=2, judges_enabled=False, seed=5,
    )

    assert manifest.system_prompt_sha256 == sha256_text(build_system_prompt(triage_max_followups()))
    assert manifest.simulator_prompt_sha256 == sha256_text(SIMULATOR_SYSTEM_PROMPT)
    assert (manifest.system_temperature, manifest.system_response_temperature) == (
        CLASSIFY_TEMPERATURE, RESPONSE_TEMPERATURE)
    assert manifest.simulator_temperature == SIMULATOR_TEMPERATURE
    assert (manifest.system_model, manifest.simulator_model) == ("m1", "m2")
    assert manifest.bootstrap_seed == 5 and manifest.judges_enabled is False


def test_parser_reads_new_flags():
    args = cli.build_parser().parse_args(
        ["run-ablation", "--variant", "lay", "--repeats", "3", "--no-judges", "--seed", "5"])

    assert (args.variant, args.repeats, args.no_judges, args.seed) == ("lay", 3, True, 5)


def test_compare_legs_command_prints_comparison(tmp_path, capsys):
    checkpoint = CheckpointStore(str(tmp_path / "checkpoint.jsonl"))
    for leg in ("off", "static"):
        for case_id in ("1", "2", "3"):
            row = ConfusionMatrixRow(case_id, "emergent", "emergent", True, False)
            checkpoint.append("original", leg, 0, row, None, None, [])

    cli.compare_legs_command(str(tmp_path / "checkpoint.jsonl"), "original", "off", "static", seed=1)

    assert "n=3" in capsys.readouterr().out
