import dataclasses
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from scripts.symptom_eval.run_manifest import (
    ManifestMismatch,
    RunManifest,
    UnmanifestedCheckpoint,
    hash_directory,
    manifest_path,
    read_manifest,
    sha256_text,
    write_or_verify_manifest,
)


def _manifest(**overrides) -> RunManifest:
    values = dict(
        system_model="openai/gpt-oss-120b", system_temperature=0.2, system_response_temperature=0.3,
        system_min_turns=3, system_context_window=10,
        simulator_model="claude-haiku-4-5", simulator_temperature=0.3,
        providers=("off", "static"), variant="original", repeats=2,
        judges_enabled=False, bootstrap_seed=20261107,
        system_prompt_sha256="a" * 64, simulator_prompt_sha256="b" * 64,
        checklists_sha256="c" * 64, harness_git_commit="abc1234",
        retry_max_attempts=2, retry_base_delay_seconds=0.25, conversation_token_cap=30000,
        breaker_enabled=False, breaker_failure_threshold=5, breaker_cooldown_seconds=30.0,
        capped_reply_sha256="e" * 64, graph_index_manifest_sha256="", semantic_model_id="",
        red_flag_floor_mode="shadow", groundedness_guard_mode="enforce", emergency_mismatch_mode="shadow",
        red_flag_list_sha256="d" * 64, retry_budget_percent=10,
    )
    values.update(overrides)
    return RunManifest(**values)


def test_manifest_path_sits_beside_checkpoint():
    assert manifest_path("/x/checkpoint.jsonl") == "/x/checkpoint.jsonl.manifest.json"


def test_first_call_writes_manifest_file(tmp_path):
    checkpoint = str(tmp_path / "checkpoint.jsonl")

    write_or_verify_manifest(checkpoint, _manifest(), "2026-11-08T10:00:00Z")

    assert os.path.exists(manifest_path(checkpoint))


def test_same_config_resumes_even_with_new_providers_commit_and_start_time(tmp_path):
    checkpoint = str(tmp_path / "checkpoint.jsonl")
    write_or_verify_manifest(checkpoint, _manifest(), "2026-11-08T10:00:00Z")

    write_or_verify_manifest(
        checkpoint,
        _manifest(providers=("off", "static", "v3"), harness_git_commit="def5678"),
        "2026-11-09T10:00:00Z",
    )


def test_changed_prompt_hash_raises_naming_field(tmp_path):
    checkpoint = str(tmp_path / "checkpoint.jsonl")
    write_or_verify_manifest(checkpoint, _manifest(), "2026-11-08T10:00:00Z")

    with pytest.raises(ManifestMismatch, match="system_prompt_sha256"):
        write_or_verify_manifest(
            checkpoint, _manifest(system_prompt_sha256="d" * 64), "2026-11-09T10:00:00Z"
        )


def test_changed_repeats_raises(tmp_path):
    checkpoint = str(tmp_path / "checkpoint.jsonl")
    write_or_verify_manifest(checkpoint, _manifest(), "2026-11-08T10:00:00Z")

    with pytest.raises(ManifestMismatch, match="repeats"):
        write_or_verify_manifest(checkpoint, _manifest(repeats=3), "2026-11-09T10:00:00Z")


def test_every_non_exempt_field_is_checked(tmp_path):
    exempt = {"providers", "harness_git_commit"}
    base = _manifest()
    changes = {
        "system_model": "other", "system_temperature": 0.9, "system_response_temperature": 0.9, "system_min_turns": 9, "system_context_window": 9, "simulator_model": "other",
        "simulator_temperature": 0.9, "variant": "lay", "repeats": 9, "judges_enabled": True,
        "bootstrap_seed": 1, "system_prompt_sha256": "z", "simulator_prompt_sha256": "z",
        "checklists_sha256": "z",
        "retry_max_attempts": 9, "retry_base_delay_seconds": 9.0, "conversation_token_cap": 9,
        "breaker_enabled": True, "breaker_failure_threshold": 9, "breaker_cooldown_seconds": 9.0,
        "capped_reply_sha256": "z", "graph_index_manifest_sha256": "z", "semantic_model_id": "other-model",
        "red_flag_floor_mode": "enforce", "groundedness_guard_mode": "off", "emergency_mismatch_mode": "off",
        "red_flag_list_sha256": "z", "retry_budget_percent": 99,
    }
    assert set(changes) == {f.name for f in dataclasses.fields(base)} - exempt

    for index, (name, value) in enumerate(changes.items()):
        checkpoint = str(tmp_path / f"cp{index}.jsonl")
        write_or_verify_manifest(checkpoint, base, "t")
        with pytest.raises(ManifestMismatch, match=name):
            write_or_verify_manifest(checkpoint, dataclasses.replace(base, **{name: value}), "t")


def test_hash_directory_changes_when_a_file_changes(tmp_path):
    (tmp_path / "1.json").write_text("{}")
    before = hash_directory(str(tmp_path))

    (tmp_path / "1.json").write_text('{"a": 1}')

    assert hash_directory(str(tmp_path)) != before


def test_hash_directory_ignores_creation_order_and_dotfiles(tmp_path):
    first, second = tmp_path / "a", tmp_path / "b"
    first.mkdir()
    second.mkdir()
    (first / "1.json").write_text("one")
    (first / "2.json").write_text("two")
    (second / "2.json").write_text("two")
    (second / "1.json").write_text("one")
    (second / ".gitkeep").write_text("")

    assert hash_directory(str(first)) == hash_directory(str(second))


def test_sha256_text_is_hex_digest():
    assert sha256_text("a") == "ca978112ca1bbdcafac231b39a23dc4da786eff8147c4e72b9807785afee48bb"


OLD_LINE = '{"provider": "off", "case_id": "1"}\n'


def test_existing_checkpoint_without_manifest_is_refused(tmp_path):
    checkpoint = tmp_path / "checkpoint.jsonl"
    checkpoint.write_text(OLD_LINE)

    with pytest.raises(UnmanifestedCheckpoint, match="adopt"):
        write_or_verify_manifest(str(checkpoint), _manifest(), "t")

    assert not os.path.exists(manifest_path(str(checkpoint)))


def test_adopting_a_legacy_checkpoint_writes_the_manifest(tmp_path):
    checkpoint = tmp_path / "checkpoint.jsonl"
    checkpoint.write_text(OLD_LINE)

    write_or_verify_manifest(str(checkpoint), _manifest(), "t", adopt_legacy=True)

    assert os.path.exists(manifest_path(str(checkpoint)))


def test_blank_checkpoint_file_needs_no_adoption(tmp_path):
    checkpoint = tmp_path / "checkpoint.jsonl"
    checkpoint.write_text("\n")

    write_or_verify_manifest(str(checkpoint), _manifest(), "t")


def test_read_manifest_is_none_when_absent_and_a_dict_when_present(tmp_path):
    checkpoint = str(tmp_path / "checkpoint.jsonl")
    assert read_manifest(checkpoint) is None

    write_or_verify_manifest(checkpoint, _manifest(), "t")

    assert read_manifest(checkpoint)["variant"] == "original"


@pytest.mark.parametrize("field,changed", [
    ("retry_max_attempts", 3),
    ("retry_base_delay_seconds", 0.5),
    ("conversation_token_cap", 12345),
    ("breaker_enabled", True),
    ("breaker_failure_threshold", 9),
    ("breaker_cooldown_seconds", 60.0),
    ("capped_reply_sha256", "f" * 64),
    ("red_flag_floor_mode", "enforce"),
    ("groundedness_guard_mode", "off"),
    ("emergency_mismatch_mode", "off"),
    ("red_flag_list_sha256", "f" * 64),
    ("retry_budget_percent", 20),
])
def test_a_changed_guard_setting_is_refused_on_resume(tmp_path, field, changed):
    checkpoint = str(tmp_path / "checkpoint.jsonl")
    write_or_verify_manifest(checkpoint, _manifest(), "2026-11-08T10:00:00Z")

    with pytest.raises(ManifestMismatch, match=field):
        write_or_verify_manifest(checkpoint, _manifest(**{field: changed}), "2026-11-09T10:00:00Z")


def test_a_manifest_written_before_the_guard_settings_existed_is_refused(tmp_path):
    checkpoint = str(tmp_path / "checkpoint.jsonl")
    write_or_verify_manifest(checkpoint, _manifest(), "2026-11-08T10:00:00Z")
    path = manifest_path(checkpoint)
    import json
    stored = json.load(open(path))
    del stored["conversation_token_cap"]
    json.dump(stored, open(path, "w"))

    with pytest.raises(ManifestMismatch, match="conversation_token_cap"):
        write_or_verify_manifest(checkpoint, _manifest(), "2026-11-09T10:00:00Z")


def test_manifest_mismatch_when_the_index_changes_between_resumes(tmp_path):
    checkpoint = str(tmp_path / "cp.jsonl")
    base = _manifest(providers=("off", "neo4j_semantic"), graph_index_manifest_sha256="a" * 64, semantic_model_id="biolord")
    write_or_verify_manifest(checkpoint, base, "t")
    with pytest.raises(ManifestMismatch, match="graph_index_manifest_sha256"):
        write_or_verify_manifest(checkpoint, dataclasses.replace(base, graph_index_manifest_sha256="b" * 64), "t")
    with pytest.raises(ManifestMismatch, match="semantic_model_id"):
        write_or_verify_manifest(checkpoint, dataclasses.replace(base, semantic_model_id="bge_small"), "t")
