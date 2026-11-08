import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from llm.anthropic_client import AnthropicClient
from llm.groq_client import GroqClient
from scripts.symptom_eval import cli
from scripts.symptom_eval.ablation import CheckpointStore
from scripts.symptom_eval.dry_run import FakeSystem

VIGNETTE_COUNT = 27
LEGS = ("off", "static")
REPEATS = 2
TOTAL_CONVERSATIONS = VIGNETTE_COUNT * len(LEGS) * REPEATS


class _Interrupted(Exception):
    pass


class _FlakySystem:
    """Wraps FakeSystem: counts every call and dies once `die_after` calls have been made."""

    def __init__(self, provider, counter, die_after=None):
        self._inner = FakeSystem(provider)
        self._counter = counter
        self._die_after = die_after

    def respond(self, patient_message, history):
        if self._die_after is not None and self._counter["calls"] >= self._die_after:
            raise _Interrupted()
        self._counter["calls"] += 1
        return self._inner.respond(patient_message, history)


def _dependencies(counter, die_after=None):
    fakes = cli.dry_run_dependencies()
    return cli.RunDependencies(
        system_factory=lambda provider: _FlakySystem(provider, counter, die_after),
        simulator=fakes.simulator, system_model=fakes.system_model, simulator_model=fakes.simulator_model,
    )


@pytest.fixture
def no_real_providers(monkeypatch):
    def explode(*args, **kwargs):
        raise AssertionError("a paid provider client was constructed during a dry run")

    monkeypatch.setattr(GroqClient, "__init__", explode)
    monkeypatch.setattr(AnthropicClient, "__init__", explode)


@pytest.mark.parametrize("variant", ["original", "lay"])
def test_dry_run_end_to_end_with_resume_and_zero_provider_calls(tmp_path, no_real_providers, capsys, variant):
    checkpoint = str(tmp_path / "checkpoint.jsonl")
    options = dict(
        limit=None, checkpoint_path=checkpoint, providers=LEGS, variant=variant, repeats=REPEATS,
        judges=False, results_dir=str(tmp_path), dry_run=True,
    )

    first = {"calls": 0}
    with pytest.raises(_Interrupted):
        cli.run_ablation_command(**options, dependencies=_dependencies(first, die_after=30))
    assert len(CheckpointStore(checkpoint).done) == 30  # progress was saved up to the interruption

    resumed = {"calls": 0}
    cli.run_ablation_command(**options, dependencies=_dependencies(resumed))
    assert resumed["calls"] == TOTAL_CONVERSATIONS - 30  # completed keys were not recomputed
    assert len(CheckpointStore(checkpoint).done) == TOTAL_CONVERSATIONS

    capsys.readouterr()
    cli.compare_legs_command(checkpoint, variant, "off", "static", seed=1)
    assert f"n={VIGNETTE_COUNT}" in capsys.readouterr().out


def test_dry_run_defaults_to_a_temp_directory_and_labels_output(tmp_path, monkeypatch, no_real_providers, capsys):
    monkeypatch.setattr(cli.tempfile, "mkdtemp", lambda prefix: str(tmp_path / "dry"))
    os.makedirs(tmp_path / "dry")

    cli.run_ablation_command(limit=1, providers=("off",), dry_run=True)

    output = capsys.readouterr().out
    assert "DRY RUN" in output
    assert cli.RESULTS_DIR not in output
    assert os.path.exists(tmp_path / "dry" / "checkpoint.jsonl")


def test_dry_run_never_builds_judges(tmp_path, monkeypatch, no_real_providers):
    monkeypatch.setattr(cli, "DeepEvalFeaturePresenceJudge", lambda: pytest.fail("judge built in a dry run"))
    monkeypatch.setattr(cli, "DeepEvalRubricJudge", lambda: pytest.fail("judge built in a dry run"))

    cli.run_ablation_command(
        limit=1, checkpoint_path=str(tmp_path / "cp.jsonl"), providers=("off",), judges=True,
        results_dir=str(tmp_path), dry_run=True,
    )


def test_fake_system_is_deterministic_per_provider_and_opening():
    first = FakeSystem("off").respond("I feel dizzy", [])
    again = FakeSystem("off").respond("I feel dizzy", [])

    assert (first.severity, first.graph_context_matched) == (again.severity, again.graph_context_matched)
