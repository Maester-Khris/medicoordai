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
from scripts.symptom_eval.run_manifest import (
    ManifestMismatch,
    UnmanifestedCheckpoint,
    manifest_path,
    sha256_text,
)
from llm.retry import BASE_DELAY_SECONDS
from scripts.symptom_eval.system_under_test import SystemTurnResult
from services.llm_agent import (
    CLASSIFY_TEMPERATURE,
    capped_reply_fingerprint,
    RESPONSE_TEMPERATURE,
    triage_context_window,
    triage_max_followups,
    triage_min_turns,
)


class _FakeSimulator:
    def reply(self, vignette, system_question, history):
        return "more info"


class _ManifestWatchingSystem:
    """Records whether the manifest already existed when the first turn ran."""

    def __init__(self, checkpoint_path):
        self._checkpoint_path = checkpoint_path
        self.manifest_existed_at_first_call = None

    def respond(self, patient_message, history, conversation_id=None):
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
    assert (manifest.system_min_turns, manifest.system_context_window) == (
        triage_min_turns(), triage_context_window())


def test_manifest_records_the_guard_settings_the_agent_will_use(monkeypatch):
    monkeypatch.setenv("LLM_CONVERSATION_TOKEN_CAP", "1234")
    monkeypatch.setenv("LLM_RETRY_ATTEMPTS", "3")
    monkeypatch.setenv("LLM_BREAKER_FAILURES", "7")
    monkeypatch.setenv("LLM_BREAKER_COOLDOWN_SECONDS", "45")

    manifest = cli.build_manifest(
        system_model="m1", simulator_model="m2", providers=("off",), variant="original",
        repeats=1, judges_enabled=False, seed=5,
    )

    assert manifest.conversation_token_cap == 1234
    assert manifest.retry_max_attempts == 3
    assert (manifest.breaker_failure_threshold, manifest.breaker_cooldown_seconds) == (7, 45)
    assert manifest.retry_base_delay_seconds == BASE_DELAY_SECONDS
    assert manifest.breaker_enabled is False  # the eval runs without the breaker (spec C11)
    assert manifest.capped_reply_sha256 == sha256_text(capped_reply_fingerprint())


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


OLD_FORMAT_LINE = json.dumps({
    "provider": "off", "case_id": "1",
    "confusion_row": {"case_id": "1", "predicted": "emergent", "gold": "emergent",
                      "correct": True, "under_triaged": False},
    "coverage": None, "gain": None,
}) + "\n"


def _legacy_checkpoint(tmp_path):
    path = tmp_path / "checkpoint.jsonl"
    path.write_text(OLD_FORMAT_LINE)
    return str(path)


class TestCheckpointProvenance:
    def test_live_run_refuses_a_checkpoint_without_a_manifest(self, tmp_path):
        checkpoint = _legacy_checkpoint(tmp_path)

        with pytest.raises(UnmanifestedCheckpoint):
            _run(tmp_path, _ManifestWatchingSystem(checkpoint), checkpoint_path=checkpoint)

        assert open(checkpoint).read() == OLD_FORMAT_LINE  # nothing was appended

    def test_adopt_flag_lets_a_live_run_continue_a_legacy_checkpoint(self, tmp_path):
        checkpoint = _legacy_checkpoint(tmp_path)

        _run(tmp_path, _ManifestWatchingSystem(checkpoint), checkpoint_path=checkpoint,
             providers=("static",), adopt_legacy_checkpoint=True)

        assert os.path.exists(manifest_path(checkpoint))

    def test_dry_run_refuses_a_checkpoint_without_a_manifest(self, tmp_path):
        checkpoint = _legacy_checkpoint(tmp_path)

        with pytest.raises(UnmanifestedCheckpoint):
            cli.run_ablation_command(limit=1, checkpoint_path=checkpoint, providers=("off",),
                                     results_dir=str(tmp_path), dry_run=True)

    def test_dry_run_refuses_a_checkpoint_under_the_results_directory(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cli, "RESULTS_DIR", str(tmp_path / "results"))

        with pytest.raises(SystemExit, match="results"):
            cli.run_ablation_command(limit=1, checkpoint_path=str(tmp_path / "results" / "cp.jsonl"),
                                     providers=("off",), dry_run=True)

    def test_compare_legs_warns_when_there_is_no_manifest(self, tmp_path, capsys):
        checkpoint = CheckpointStore(str(tmp_path / "checkpoint.jsonl"))
        for leg in ("off", "static"):
            for case_id in ("1", "2"):
                row = ConfusionMatrixRow(case_id, "emergent", "emergent", True, False)
                checkpoint.append("original", leg, 0, row, None, None, [])

        cli.compare_legs_command(str(tmp_path / "checkpoint.jsonl"), "original", "off", "static", seed=None)

        assert "WARNING" in capsys.readouterr().out

    def test_compare_legs_labels_dry_runs_and_uses_the_manifest_seed(self, tmp_path, capsys):
        checkpoint = str(tmp_path / "checkpoint.jsonl")
        cli.run_ablation_command(limit=3, checkpoint_path=checkpoint, providers=("off", "static"),
                                 seed=5, dry_run=True)
        capsys.readouterr()

        cli.compare_legs_command(checkpoint, "original", "off", "static", seed=None)

        output = capsys.readouterr().out
        assert "DRY RUN" in output
        assert "seed 5" in output


def test_main_turns_a_provenance_error_into_a_clean_exit(tmp_path, monkeypatch):
    checkpoint = _legacy_checkpoint(tmp_path)
    monkeypatch.setattr(sys, "argv", ["cli", "run-ablation", "--dry-run", "--checkpoint", checkpoint])

    with pytest.raises(SystemExit, match="no manifest"):
        cli.main()


def test_manifest_has_empty_semantic_fields_without_a_semantic_leg(monkeypatch):
    monkeypatch.setenv("SEMANTIC_INDEX_DIR", "/should/not/be/read")
    manifest = cli.build_manifest(
        system_model="m1", simulator_model="m2", providers=("off", "static"), variant="original",
        repeats=1, judges_enabled=False, seed=5,
    )
    assert (manifest.graph_index_manifest_sha256, manifest.semantic_model_id) == ("", "")


def test_build_manifest_reads_the_index_manifest_hash(monkeypatch, tmp_path):
    import hashlib, json
    index_dir = tmp_path / "idx"
    index_dir.mkdir()
    body = json.dumps({"model_id": "biolord", "rows": 3}).encode()
    (index_dir / "manifest.json").write_bytes(body)
    monkeypatch.setenv("SEMANTIC_INDEX_DIR", str(index_dir))
    manifest = cli.build_manifest(
        system_model="m1", simulator_model="m2", providers=("off", "neo4j_semantic"), variant="original",
        repeats=1, judges_enabled=False, seed=5,
    )
    assert manifest.graph_index_manifest_sha256 == hashlib.sha256(body).hexdigest()
    assert manifest.semantic_model_id == "biolord"


def test_a_semantic_leg_without_a_readable_index_fails_before_any_spend(monkeypatch, tmp_path):
    monkeypatch.delenv("SEMANTIC_INDEX_DIR", raising=False)
    kwargs = dict(system_model="m1", simulator_model="m2", providers=("off", "neo4j_semantic"), variant="original",
                  repeats=1, judges_enabled=False, seed=5)
    with pytest.raises(ValueError, match="SEMANTIC_INDEX_DIR"):
        cli.build_manifest(**kwargs)
    monkeypatch.setenv("SEMANTIC_INDEX_DIR", str(tmp_path / "missing"))
    with pytest.raises(ValueError, match="manifest"):
        cli.build_manifest(**kwargs)
