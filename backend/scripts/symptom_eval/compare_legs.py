"""
CompareLegs — turns two legs of a checkpoint into a paired comparison.

Unit of analysis is the vignette: a vignette's rate is the mean over its
repeats. Only vignettes present in both legs and not excluded are compared,
and n is always reported. A conversation that never classified
(predicted is None) is not counted as under-triaged, so it is counted and
reported separately — otherwise a leg that never answers would look safe.
"""
from collections import defaultdict
from dataclasses import dataclass

from scripts.symptom_eval.ablation import CheckpointStore
from scripts.symptom_eval.paired_stats import (
    BootstrapResult,
    McNemarResult,
    mcnemar_exact,
    paired_bootstrap_diff,
)

MIN_SHARED_VIGNETTES = 2
UNDER_TRIAGED_RATE_THRESHOLD = 0.5  # a tie counts as under-triaged: the conservative direction


@dataclass(frozen=True)
class MetricComparison:
    rate_a: float
    rate_b: float
    bootstrap: BootstrapResult
    mcnemar: McNemarResult | None


@dataclass(frozen=True)
class LegComparison:
    variant: str
    leg_a: str
    leg_b: str
    n: int
    under_triage: MetricComparison
    accuracy: MetricComparison
    unclassified_a: int
    unclassified_b: int


def _entries_by_case(checkpoint: CheckpointStore, variant: str, leg: str) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for entry in checkpoint.entries_for(variant, leg):
        grouped[entry["case_id"]].append(entry["confusion_row"])
    return grouped


def _rates(rows_by_case: dict[str, list[dict]], case_ids: list[str], field: str) -> list[float]:
    return [
        sum(1 for row in rows_by_case[case_id] if row[field]) / len(rows_by_case[case_id])
        for case_id in case_ids
    ]


def _unclassified(rows_by_case: dict[str, list[dict]], case_ids: list[str]) -> int:
    return sum(1 for case_id in case_ids for row in rows_by_case[case_id] if row["predicted"] is None)


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def compare_legs(
    checkpoint: CheckpointStore,
    variant: str,
    leg_a: str,
    leg_b: str,
    excluded_case_ids: frozenset[str],
    seed: int,
) -> LegComparison:
    rows_a = _entries_by_case(checkpoint, variant, leg_a)
    rows_b = _entries_by_case(checkpoint, variant, leg_b)
    shared = sorted((set(rows_a) & set(rows_b)) - excluded_case_ids)
    if len(shared) < MIN_SHARED_VIGNETTES:
        raise ValueError(
            f"need at least {MIN_SHARED_VIGNETTES} vignettes in both '{leg_a}' and '{leg_b}' "
            f"({variant}); found {len(shared)}"
        )

    under_a, under_b = _rates(rows_a, shared, "under_triaged"), _rates(rows_b, shared, "under_triaged")
    correct_a, correct_b = _rates(rows_a, shared, "correct"), _rates(rows_b, shared, "correct")
    return LegComparison(
        variant=variant,
        leg_a=leg_a,
        leg_b=leg_b,
        n=len(shared),
        under_triage=MetricComparison(
            rate_a=_mean(under_a),
            rate_b=_mean(under_b),
            bootstrap=paired_bootstrap_diff(under_a, under_b, seed),
            mcnemar=mcnemar_exact(
                [rate >= UNDER_TRIAGED_RATE_THRESHOLD for rate in under_a],
                [rate >= UNDER_TRIAGED_RATE_THRESHOLD for rate in under_b],
            ),
        ),
        accuracy=MetricComparison(
            rate_a=_mean(correct_a),
            rate_b=_mean(correct_b),
            bootstrap=paired_bootstrap_diff(correct_a, correct_b, seed),
            mcnemar=None,
        ),
        unclassified_a=_unclassified(rows_a, shared),
        unclassified_b=_unclassified(rows_b, shared),
    )


def _format_metric(name: str, c: LegComparison, m: MetricComparison) -> list[str]:
    b = m.bootstrap
    lines = [
        f"{name}: {c.leg_a}={m.rate_a:.3f}  {c.leg_b}={m.rate_b:.3f}  "
        f"diff={b.diff:+.3f}  95% interval [{b.low:+.3f}, {b.high:+.3f}] "
        f"({b.resamples} resamples, seed {b.seed})"
    ]
    if m.mcnemar is not None:
        lines.append(
            f"  McNemar exact: only {c.leg_a}={m.mcnemar.only_a}  only {c.leg_b}={m.mcnemar.only_b}  "
            f"p={m.mcnemar.p_value:.4f}"
        )
    return lines


def format_comparison(c: LegComparison) -> str:
    lines = [f"{c.variant}: {c.leg_a} vs {c.leg_b}  n={c.n} vignettes"]
    lines += _format_metric("under-triage", c, c.under_triage)
    lines += _format_metric("accuracy", c, c.accuracy)
    lines.append(f"unclassified conversations: {c.leg_a}={c.unclassified_a}  {c.leg_b}={c.unclassified_b}")
    return "\n".join(lines)
