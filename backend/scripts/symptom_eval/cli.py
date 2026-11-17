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
import hashlib
import json
import os
import subprocess
import tempfile
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from typing import Callable

from config import (
    emergency_mismatch_mode,
    groundedness_guard_mode,
    llm_breaker_cooldown_seconds,
    llm_breaker_failures,
    llm_conversation_token_cap,
    llm_retry_attempts,
    red_flag_floor_mode,
    retry_budget_percent,
)
from llm.prompts import build_system_prompt
from llm.retry import BASE_DELAY_SECONDS
from services.red_flags import red_flag_list_sha256
from scripts.symptom_eval.ablation import AblationLegResult, CheckpointStore, TooManyFailures, run_ablation
from scripts.symptom_eval.checklist_extractor import OpenAIChecklistExtractor
from scripts.symptom_eval.compare_legs import compare_legs, format_comparison
from scripts.symptom_eval.dry_run import DRY_RUN_MODEL, FakeSimulator, FakeSystem
from scripts.symptom_eval.elicitation_coverage import DeepEvalFeaturePresenceJudge, FeaturePresenceJudgePort
from scripts.symptom_eval.information_gain import DeepEvalRubricJudge, RubricJudgePort
from scripts.symptom_eval.pacing import Pacer, PacedSystem
from scripts.symptom_eval.patient_simulator import (
    SIMULATOR_SYSTEM_PROMPT,
    SIMULATOR_TEMPERATURE,
    PatientSimulatorPort,
    simulator_from_env,
)
from scripts.symptom_eval.run_manifest import (
    ManifestMismatch,
    RunManifest,
    UnmanifestedCheckpoint,
    hash_directory,
    read_manifest,
    sha256_text,
    write_or_verify_manifest,
)
from scripts.symptom_eval.system_under_test import (
    EVAL_BREAKER_ENABLED, LiveLLMAgentAdapter, SystemUnderTestPort, eval_system_model_label,
)
from scripts.symptom_eval.vignette_loader import (
    CHECKLISTS_DIR,
    VARIANTS,
    checklists_dir_for,
    load_all_vignettes,
    load_raw_vignettes,
)
from services.llm_agent import (
    CLASSIFY_TEMPERATURE,
    RESPONSE_TEMPERATURE,
    capped_reply_fingerprint,
    triage_context_window,
    triage_max_followups,
    triage_min_turns,
)

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
    simulator = simulator_from_env()
    return RunDependencies(
        system_factory=lambda provider: LiveLLMAgentAdapter(graph_rag_provider=provider),
        simulator=simulator,
        system_model=eval_system_model_label(),
        simulator_model=simulator.model_name,
    )


def dry_run_dependencies() -> RunDependencies:
    return RunDependencies(
        system_factory=FakeSystem, simulator=FakeSimulator(),
        system_model=DRY_RUN_MODEL, simulator_model=DRY_RUN_MODEL,
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


def semantic_index_fields(providers: tuple[str, ...]) -> tuple[str, str]:
    """(sha256 of the semantic index manifest file, its model id), or ("", "") with no neo4j_semantic leg.

    A semantic leg's results depend on the index it searched, so the run must say which one; a missing or
    unreadable index fails here, before the first paid call, instead of after hours of conversations."""
    if "neo4j_semantic" not in providers:
        return "", ""
    index_dir = os.environ.get("SEMANTIC_INDEX_DIR")
    if not index_dir:
        raise ValueError("a neo4j_semantic leg needs SEMANTIC_INDEX_DIR to record which index it ran against")
    path = os.path.join(index_dir, "manifest.json")
    try:
        with open(path, "rb") as f:
            raw = f.read()
        model_id = json.loads(raw)["model_id"]
    except (OSError, ValueError, KeyError) as error:
        raise ValueError(f"cannot read the semantic index manifest at {path}: {type(error).__name__}") from error
    return hashlib.sha256(raw).hexdigest(), str(model_id)


def build_manifest(
    *, system_model: str, simulator_model: str, providers: tuple[str, ...], variant: str,
    repeats: int, judges_enabled: bool, seed: int,
) -> RunManifest:
    index_sha256, semantic_model_id = semantic_index_fields(providers)
    return RunManifest(
        system_model=system_model,
        system_temperature=CLASSIFY_TEMPERATURE,
        system_response_temperature=RESPONSE_TEMPERATURE,
        system_min_turns=triage_min_turns(),
        system_context_window=triage_context_window(),
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
        retry_max_attempts=llm_retry_attempts(),
        retry_base_delay_seconds=BASE_DELAY_SECONDS,
        conversation_token_cap=llm_conversation_token_cap(),
        breaker_enabled=EVAL_BREAKER_ENABLED,
        breaker_failure_threshold=llm_breaker_failures(),
        breaker_cooldown_seconds=llm_breaker_cooldown_seconds(),
        capped_reply_sha256=sha256_text(capped_reply_fingerprint()),
        graph_index_manifest_sha256=index_sha256,
        semantic_model_id=semantic_model_id,
        red_flag_floor_mode=red_flag_floor_mode(),
        groundedness_guard_mode=groundedness_guard_mode(),
        emergency_mismatch_mode=emergency_mismatch_mode(),
        red_flag_list_sha256=red_flag_list_sha256(),
        retry_budget_percent=retry_budget_percent(),
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
    results_dir: str | None = None,
    dependencies: RunDependencies | None = None,
    dry_run: bool = False,
    adopt_legacy_checkpoint: bool = False,
    cases: tuple[str, ...] | None = None,
    min_gap_s: float = 0.0,
    skip_failed: bool = False,
) -> None:
    label = "DRY RUN " if dry_run else ""
    if dry_run:
        if checkpoint_path and _is_under(checkpoint_path, RESULTS_DIR):
            raise SystemExit(f"--dry-run must not write under {RESULTS_DIR}: its fake numbers would look real.")
        judges = False  # the judges are LLM calls; a dry run makes none
        results_dir = results_dir or tempfile.mkdtemp(prefix="eval_dry_run_")
        dependencies = dependencies or dry_run_dependencies()
        print("DRY RUN: fake system and simulator, no provider calls. These numbers are not results.")
    results_dir = results_dir or RESULTS_DIR
    vignettes = load_all_vignettes(variant=variant)
    if limit:
        vignettes = vignettes[:limit]
    if cases:
        known = {v.case_id for v in vignettes}
        unknown = [c for c in cases if c not in known]
        if unknown:
            raise SystemExit(f"Unknown case id(s) for variant {variant!r}: {', '.join(unknown)}")
        vignettes = [v for v in vignettes if v.case_id in cases]
    if not vignettes:
        raise SystemExit(
            "No vignettes with authored checklists found — run "
            "'extract-checklists' first, review the output, then re-run."
        )

    os.makedirs(results_dir, exist_ok=True)
    checkpoint_path = checkpoint_path or os.path.join(results_dir, "checkpoint.jsonl")
    dependencies = dependencies or live_dependencies()
    if min_gap_s > 0:
        pacer, make_system = Pacer(min_gap_s), dependencies.system_factory
        dependencies = replace(dependencies, system_factory=lambda provider: PacedSystem(make_system(provider), pacer))

    # The manifest goes to disk before the first LLM call, and a resume under a
    # different configuration stops here rather than mixing two runs.
    write_or_verify_manifest(
        checkpoint_path,
        build_manifest(
            system_model=dependencies.system_model, simulator_model=dependencies.simulator_model,
            providers=providers, variant=variant, repeats=repeats, judges_enabled=judges, seed=seed,
        ),
        started_at=datetime.now(timezone.utc).isoformat(),
        adopt_legacy=adopt_legacy_checkpoint,
    )

    checkpoint = CheckpointStore(checkpoint_path)
    already_done = len(checkpoint.done)
    if already_done:
        print(f"{label}Resuming from checkpoint {checkpoint_path} — {already_done} vignette-legs already recorded")

    feature_judge, rubric_judge = build_judges(judges)
    skipped: list[str] = []

    def report_failure(conversation_id: str, error: Exception) -> None:
        skipped.append(conversation_id)
        print(f"{label}SKIPPED {conversation_id}: {type(error).__name__}: {str(error)[:200]}")

    try:
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
            on_failure=report_failure if skip_failed else None,
        )
    except TooManyFailures as error:
        raise SystemExit(f"{error}. Stopped; rerun with the same checkpoint to resume.") from error

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = os.path.join(results_dir, f"ablation_results_{stamp}.json")
    with open(path, "w") as f:
        json.dump([serialize_leg(leg) for leg in legs], f, indent=2)

    for leg in legs:
        print(f"{label}{leg.provider}: {leg.confusion_matrix}")
    print(f"{label}Full results written to {path}")
    if skipped:
        print(f"{label}{len(skipped)} conversation(s) skipped, not in the checkpoint: {', '.join(skipped)}")


def _is_under(path: str, directory: str) -> bool:
    return os.path.realpath(path).startswith(os.path.realpath(directory) + os.sep)


def _provenance_lines(manifest: dict | None) -> list[str]:
    if manifest is None:
        return ["WARNING: no manifest beside this checkpoint, so the configuration behind these numbers is unknown."]
    lines = []
    if manifest["system_model"] == DRY_RUN_MODEL:
        lines.append("DRY RUN: fake system and simulator. These numbers are not results.")
    lines.append(
        f"manifest: system={manifest['system_model']} simulator={manifest['simulator_model']} "
        f"variant={manifest['variant']} repeats={manifest['repeats']} judges={manifest['judges_enabled']} "
        f"commit={manifest['harness_git_commit'][:7]}"
    )
    return lines


def compare_legs_command(
    checkpoint_path: str, variant: str, leg_a: str, leg_b: str, seed: int | None = None
) -> None:
    manifest = read_manifest(checkpoint_path)
    if seed is None:
        seed = manifest["bootstrap_seed"] if manifest else BOOTSTRAP_SEED
    for line in _provenance_lines(manifest):
        print(line)
    excluded = frozenset(v.case_id for v in load_all_vignettes(variant=variant) if v.pairing_exclusion)
    comparison = compare_legs(CheckpointStore(checkpoint_path), variant, leg_a, leg_b, excluded, seed)
    print(format_comparison(comparison))


PRIMARY_COMPARISON = ("off", "neo4j_semantic", "coverage_answerable")
JUDGE_MODEL_FOR_RESCORE = "gpt-4o-mini"
AGREEMENT_MODEL = "gpt-4.1-mini"


def rescore_command(
    checkpoint_path: str, variant: str, out_path: str, *, workers: int = 8, cache_path: str | None = None,
    agreement_per_class: int = 0, seed: int = BOOTSTRAP_SEED,
    judge_factory: Callable[[], FeaturePresenceJudgePort] | None = None,
    second_judge_factory: Callable[[], FeaturePresenceJudgePort] | None = None,
) -> dict:
    """Judge saved conversations for elicitation coverage; no system or simulator calls.
    The judge factories are injectable so tests run without a provider."""
    from scripts.symptom_eval import rescore

    judge_factory = judge_factory or DeepEvalFeaturePresenceJudge
    store = CheckpointStore(checkpoint_path)
    providers = sorted({provider for (v, provider) in store.entries if v == variant})
    entries = [e for p in providers for e in store.entries_for(variant, p)]
    vignettes = {v.case_id: v for v in load_all_vignettes(variant=variant)}
    cache = rescore.VerdictCache(cache_path, salt=JUDGE_MODEL_FOR_RESCORE)
    results = rescore.rescore_entries(vignettes, entries, judge_factory, workers=workers, cache=cache)

    legs = {
        p: {
            "n": sum(1 for r in results if r.provider == p),
            "coverage_all": _mean([r.coverage_all for r in results if r.provider == p]),
            "coverage_answerable": _mean([r.coverage_answerable for r in results if r.provider == p]),
        }
        for p in providers
    }
    comparisons = []
    for a, b in (("off", "static"), ("off", "neo4j_semantic"), ("static", "neo4j_semantic")):
        if a in legs and b in legs:
            for metric in ("coverage_answerable", "coverage_all"):
                c = rescore.compare_coverage(results, a, b, metric, seed)
                comparisons.append({**asdict(c), "primary": (a, b, metric) == PRIMARY_COMPARISON})
    agreement = None
    if agreement_per_class > 0:
        second = (second_judge_factory or (lambda: DeepEvalFeaturePresenceJudge(model=AGREEMENT_MODEL)))()
        agreement = {**asdict(rescore.judge_agreement(cache, second, agreement_per_class, seed)),
                     "second_model": AGREEMENT_MODEL}
    report = {
        "checkpoint": checkpoint_path, "variant": variant, "judge_model": JUDGE_MODEL_FOR_RESCORE, "seed": seed,
        "legs": legs, "comparisons": comparisons, "agreement": agreement,
        "entries": [
            {"provider": r.provider, "case_id": r.case_id, "repeat": r.repeat,
             "coverage_all": r.coverage_all, "coverage_answerable": r.coverage_answerable,
             "verdicts": [asdict(v) | {"elicited": v.elicited} for v in r.verdicts]}
            for r in results
        ],
    }
    with open(out_path, "w") as f:
        json.dump(report, f, indent=1)
    return report


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


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
    run_parser.add_argument("--dry-run", action="store_true",
                            help="Use fake system and simulator, write to a temp directory, make no provider "
                                 "calls and run no judges. Output is labelled DRY RUN and is not a result.")
    run_parser.add_argument("--adopt-legacy-checkpoint", action="store_true",
                            help="Continue a checkpoint that has results but no manifest, certifying it with "
                                 "today's configuration. Off by default: its true configuration is unknown.")
    run_parser.add_argument("--seed", type=int, default=BOOTSTRAP_SEED, help="Bootstrap seed, recorded in the manifest.")
    run_parser.add_argument("--cases", type=str, default=None,
                            help="Comma-separated case ids to run (for example 1,2,5); default is every vignette.")
    run_parser.add_argument("--min-gap-s", type=float, default=0.0,
                            help="Minimum seconds between the system's turns, to stay under a provider's "
                                 "tokens-per-minute limit (Groq free tier: about 20).")
    run_parser.add_argument("--skip-failed", action="store_true",
                            help="Report and skip a conversation whose provider call fails instead of stopping "
                                 "the run (for CI). Skipped ones stay out of the checkpoint; 3 failures in a row "
                                 "still stop it. Off by default: paid runs fail loudly.")

    compare_parser = subparsers.add_parser("compare-legs")
    compare_parser.add_argument("--checkpoint", type=str, required=True)
    compare_parser.add_argument("--variant", choices=VARIANTS, default="original")
    compare_parser.add_argument("--a", type=str, required=True, dest="leg_a")
    compare_parser.add_argument("--b", type=str, required=True, dest="leg_b")
    compare_parser.add_argument("--seed", type=int, default=None,
                                help="Bootstrap seed (default: the one recorded in the checkpoint's manifest).")
    rescore_parser = subparsers.add_parser(
        "rescore", help="Judge saved conversations for elicitation coverage (OpenAI judge calls; no system calls).")
    rescore_parser.add_argument("--checkpoint", type=str, required=True)
    rescore_parser.add_argument("--variant", choices=VARIANTS, default="lay")
    rescore_parser.add_argument("--out", type=str, required=True)
    rescore_parser.add_argument("--workers", type=int, default=8)
    rescore_parser.add_argument("--cache", type=str, default=None,
                                help="JSONL file of judge verdicts; a rerun only pays for new (fact, text) pairs.")
    rescore_parser.add_argument("--agreement-per-class", type=int, default=0,
                                help="Verdicts per class (present, absent) a second judge re-judges, to report how "
                                     "far the first judge can be trusted. 0 = off.")
    rescore_parser.add_argument("--seed", type=int, default=BOOTSTRAP_SEED)
    return parser


def main() -> None:
    args = build_parser().parse_args()

    if args.command == "extract-checklists":
        extract_checklists()
    elif args.command == "run-ablation":
        try:
            run_ablation_command(
                args.limit, args.checkpoint, tuple(p.strip() for p in args.providers.split(",")),
                variant=args.variant, repeats=args.repeats, judges=not args.no_judges, seed=args.seed,
                dry_run=args.dry_run, adopt_legacy_checkpoint=args.adopt_legacy_checkpoint,
                cases=tuple(c.strip() for c in args.cases.split(",")) if args.cases else None,
                min_gap_s=args.min_gap_s, skip_failed=args.skip_failed,
            )
        except (ManifestMismatch, UnmanifestedCheckpoint) as error:
            raise SystemExit(str(error)) from error
    elif args.command == "rescore":
        report = rescore_command(args.checkpoint, args.variant, args.out, workers=args.workers,
                                 cache_path=args.cache, agreement_per_class=args.agreement_per_class, seed=args.seed)
        print(json.dumps({k: report[k] for k in ("legs", "comparisons", "agreement")}, indent=1))
    elif args.command == "compare-legs":
        compare_legs_command(args.checkpoint, args.variant, args.leg_a, args.leg_b, args.seed)


if __name__ == "__main__":
    main()
