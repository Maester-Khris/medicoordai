"""
Composition root ("Main" per Clean Architecture §6) — the only file in this
package allowed to import every concrete adapter and wire them together. No
use case or Entity file imports anthropic/openai/deepeval/LLMAgent directly
(Global Constraints' Dependency Rule); this file is where those concrete
choices are made.

Invocation:
    doppler run --config eval -- python -m scripts.symptom_eval.cli extract-checklists
    doppler run --config eval -- python -m scripts.symptom_eval.cli run-ablation --limit 3
    doppler run --config eval -- python -m scripts.symptom_eval.cli run-ablation \
        --variant lay --repeats 3 --no-judges --providers off,static
    doppler run --config eval -- python -m scripts.symptom_eval.cli compare-legs \
        --checkpoint results/checkpoint.jsonl --variant lay --a off --b static
"""
import argparse
import json
import os
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Callable

from llm.groq_client import GroqClient
from llm.prompts import build_system_prompt
from scripts.symptom_eval.ablation import AblationLegResult, CheckpointStore, run_ablation
from scripts.symptom_eval.checklist_extractor import OpenAIChecklistExtractor
from scripts.symptom_eval.compare_legs import compare_legs, format_comparison
from scripts.symptom_eval.elicitation_coverage import DeepEvalFeaturePresenceJudge, FeaturePresenceJudgePort
from scripts.symptom_eval.information_gain import DeepEvalRubricJudge, RubricJudgePort
from scripts.symptom_eval.patient_simulator import (
    SIMULATOR_SYSTEM_PROMPT,
    SIMULATOR_TEMPERATURE,
    AnthropicPatientSimulator,
    PatientSimulatorPort,
)
from scripts.symptom_eval.run_manifest import RunManifest, hash_directory, sha256_text, write_or_verify_manifest
from scripts.symptom_eval.system_under_test import LiveLLMAgentAdapter, SystemUnderTestPort
from scripts.symptom_eval.vignette_loader import (
    CHECKLISTS_DIR,
    VARIANTS,
    checklists_dir_for,
    load_all_vignettes,
    load_raw_vignettes,
)
from services.llm_agent import CLASSIFY_TEMPERATURE, RESPONSE_TEMPERATURE, triage_max_followups

RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")
BOOTSTRAP_SEED = 20261107


@dataclass
class RunDependencies:
    """The concrete collaborators of one run, plus the model names the manifest records."""

    system_factory: Callable[[str], SystemUnderTestPort]
    simulator: PatientSimulatorPort
    system_model: str
    simulator_model: str


def live_dependencies() -> RunDependencies:
    simulator = AnthropicPatientSimulator()
    return RunDependencies(
        system_factory=lambda provider: LiveLLMAgentAdapter(graph_rag_provider=provider),
        simulator=simulator,
        system_model=GroqClient().model_name,
        simulator_model=simulator.model_name,
    )


def build_judges(enabled: bool) -> tuple[FeaturePresenceJudgePort | None, RubricJudgePort | None]:
    if not enabled:
        return None, None
    return DeepEvalFeaturePresenceJudge(), DeepEvalRubricJudge()


def _git_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=os.path.dirname(__file__),
            capture_output=True, text=True, check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return result.stdout.strip()


def build_manifest(
    *, system_model: str, simulator_model: str, providers: tuple[str, ...], variant: str,
    repeats: int, judges_enabled: bool, seed: int,
) -> RunManifest:
    return RunManifest(
        system_model=system_model,
        system_temperature=CLASSIFY_TEMPERATURE,
        system_response_temperature=RESPONSE_TEMPERATURE,
        simulator_model=simulator_model,
        simulator_temperature=SIMULATOR_TEMPERATURE,
        providers=providers,
        variant=variant,
        repeats=repeats,
        judges_enabled=judges_enabled,
        bootstrap_seed=seed,
        system_prompt_sha256=sha256_text(build_system_prompt(triage_max_followups())),
        simulator_prompt_sha256=sha256_text(SIMULATOR_SYSTEM_PROMPT),
        checklists_sha256=hash_directory(checklists_dir_for(variant)),
        harness_git_commit=_git_commit(),
    )


def serialize_leg(leg: AblationLegResult) -> dict:
    return {
        "provider": leg.provider,
        "confusion_matrix": leg.confusion_matrix,
        "elicitation_coverage": [asdict(r) if r is not None else None for r in leg.elicitation_coverage],
        "information_gain": [asdict(r) if r is not None else None for r in leg.information_gain],
    }


def extract_checklists() -> None:
    extractor = OpenAIChecklistExtractor()
    os.makedirs(CHECKLISTS_DIR, exist_ok=True)
    for raw in load_raw_vignettes():
        case_id = str(raw["case_id"])
        path = os.path.join(CHECKLISTS_DIR, f"{case_id}.json")
        if os.path.exists(path):
            continue  # never silently overwrite a human-reviewed checklist
        checklist = extractor.extract(raw["scenario"], case_id)
        with open(path, "w") as f:
            json.dump(checklist, f, indent=2)
        print(f"wrote {path} — review before committing")


def run_ablation_command(
    limit: int | None,
    checkpoint_path: str | None = None,
    providers: tuple[str, ...] = ("off", "neo4j"),
    variant: str = "original",
    repeats: int = 1,
    judges: bool = True,
    seed: int = BOOTSTRAP_SEED,
    results_dir: str = RESULTS_DIR,
    dependencies: RunDependencies | None = None,
) -> None:
    vignettes = load_all_vignettes(variant=variant)
    if limit:
        vignettes = vignettes[:limit]
    if not vignettes:
        raise SystemExit(
            "No vignettes with authored checklists found — run "
            "'extract-checklists' first, review the output, then re-run."
        )

    os.makedirs(results_dir, exist_ok=True)
    checkpoint_path = checkpoint_path or os.path.join(results_dir, "checkpoint.jsonl")
    dependencies = dependencies or live_dependencies()

    # The manifest goes to disk before the first LLM call, and a resume under a
    # different configuration stops here rather than mixing two runs.
    write_or_verify_manifest(
        checkpoint_path,
        build_manifest(
            system_model=dependencies.system_model, simulator_model=dependencies.simulator_model,
            providers=providers, variant=variant, repeats=repeats, judges_enabled=judges, seed=seed,
        ),
        started_at=datetime.now(timezone.utc).isoformat(),
    )

    checkpoint = CheckpointStore(checkpoint_path)
    already_done = len(checkpoint.done)
    if already_done:
        print(f"Resuming from checkpoint {checkpoint_path} — {already_done} vignette-legs already recorded")

    feature_judge, rubric_judge = build_judges(judges)
    legs = run_ablation(
        vignettes=vignettes,
        system_factory=dependencies.system_factory,
        simulator=dependencies.simulator,
        feature_judge=feature_judge,
        rubric_judge=rubric_judge,
        providers=providers,
        checkpoint=checkpoint,
        variant=variant,
        repeats=repeats,
    )

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = os.path.join(results_dir, f"ablation_results_{stamp}.json")
    with open(path, "w") as f:
        json.dump([serialize_leg(leg) for leg in legs], f, indent=2)

    for leg in legs:
        print(f"{leg.provider}: {leg.confusion_matrix}")
    print(f"Full results written to {path}")


def compare_legs_command(checkpoint_path: str, variant: str, leg_a: str, leg_b: str, seed: int) -> None:
    excluded = frozenset(v.case_id for v in load_all_vignettes(variant=variant) if v.pairing_exclusion)
    comparison = compare_legs(CheckpointStore(checkpoint_path), variant, leg_a, leg_b, excluded, seed)
    print(format_comparison(comparison))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("extract-checklists")

    run_parser = subparsers.add_parser("run-ablation")
    run_parser.add_argument("--limit", type=int, default=None)
    run_parser.add_argument(
        "--checkpoint", type=str, default=None,
        help="Path to the JSONL checkpoint file (default: results/checkpoint.jsonl). "
             "Rerunning the same command with the same path resumes from where it left off.",
    )
    run_parser.add_argument(
        "--providers", type=str, default="off,neo4j",
        help="Comma-separated GRAPH_RAG_PROVIDER values to run as legs, e.g. "
             "'static' or 'static,off,neo4j'. Default: 'off,neo4j'.",
    )
    run_parser.add_argument("--variant", choices=VARIANTS, default="original",
                            help="Which checklist set to run: the original or the lay-language one.")
    run_parser.add_argument("--repeats", type=int, default=1, help="Conversations per vignette per leg.")
    run_parser.add_argument("--no-judges", action="store_true",
                            help="Score severity in code only; skip both LLM judges (no judge spend).")
    run_parser.add_argument("--seed", type=int, default=BOOTSTRAP_SEED, help="Bootstrap seed, recorded in the manifest.")

    compare_parser = subparsers.add_parser("compare-legs")
    compare_parser.add_argument("--checkpoint", type=str, required=True)
    compare_parser.add_argument("--variant", choices=VARIANTS, default="original")
    compare_parser.add_argument("--a", type=str, required=True, dest="leg_a")
    compare_parser.add_argument("--b", type=str, required=True, dest="leg_b")
    compare_parser.add_argument("--seed", type=int, default=BOOTSTRAP_SEED)
    return parser


def main() -> None:
    args = build_parser().parse_args()

    if args.command == "extract-checklists":
        extract_checklists()
    elif args.command == "run-ablation":
        run_ablation_command(
            args.limit, args.checkpoint, tuple(p.strip() for p in args.providers.split(",")),
            variant=args.variant, repeats=args.repeats, judges=not args.no_judges, seed=args.seed,
        )
    elif args.command == "compare-legs":
        compare_legs_command(args.checkpoint, args.variant, args.leg_a, args.leg_b, args.seed)


if __name__ == "__main__":
    main()
