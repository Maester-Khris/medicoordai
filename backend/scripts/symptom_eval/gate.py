"""CI regression gate for the production (no-graph) path.

It does not claim the system is good. It fails when a case that was reliably right on the recorded
baseline runs (the "sentinels") is now wrong, which catches a broken prompt, parser or provider swap.
Known-bad and volatile cases are reported beside it and never fail the gate. Sprint 23 step 7.

    python -m scripts.symptom_eval.gate --checkpoint <file.jsonl> --baseline <baseline.json>
"""
import argparse
import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from scripts.symptom_eval.domain import SEVERITY_RANK

PROVIDER = "off"  # the production path is the one the gate protects
MAX_NON_SAFETY_FLIPS = 1  # two or more sentinels differing from baseline fail the gate


def _predictions(rows: list[dict], variant: str) -> dict[str, list[tuple[str | None, str]]]:
    """case_id -> [(predicted, gold)] for the protected leg and variant."""
    found: dict[str, list[tuple[str | None, str]]] = defaultdict(list)
    for row in rows:
        if row.get("provider") == PROVIDER and row.get("variant") == variant:
            confusion = row["confusion_row"]
            found[str(row["case_id"])].append((confusion["predicted"], confusion["gold"]))
    return found


def build_baseline(
    rows: list[dict], sentinel_ids: list[str], watch_ids: list[str], variant: str, sources: list[str]
) -> dict:
    """The committed baseline. A sentinel must be right every time it ran: a case that wobbles cannot
    separate a regression from noise."""
    found = _predictions(rows, variant)
    sentinels = []
    for case_id in sentinel_ids:
        runs = found.get(case_id)
        if not runs:
            raise ValueError(f"case {case_id} has no runs in the history, so it cannot be a sentinel")
        gold = runs[0][1]
        right = sum(1 for predicted, _ in runs if predicted == gold)
        if right != len(runs):
            raise ValueError(f"case {case_id} was right {right} of {len(runs)} times, so it cannot be a sentinel")
        sentinels.append({"case_id": case_id, "gold": gold, "expected": gold, "stability": f"{right}/{len(runs)}"})
    watch = []
    for case_id in watch_ids:
        runs = found.get(case_id, [])
        counts = Counter(predicted for predicted, _ in runs)
        watch.append({"case_id": case_id, "gold": runs[0][1] if runs else None, "observed": dict(counts)})
    return {"version": 1, "variant": variant, "leg": PROVIDER, "sources": sources,
            "sentinels": sentinels, "watch": watch}


@dataclass
class GateResult:
    passed: bool
    reasons: list[str] = field(default_factory=list)
    sentinels: list[dict] = field(default_factory=list)
    watch: list[dict] = field(default_factory=list)


def evaluate_gate(rows: list[dict], baseline: dict) -> GateResult:
    found = _predictions(rows, baseline["variant"])
    reasons: list[str] = []
    sentinels: list[dict] = []
    flips = 0
    for sentinel in baseline["sentinels"]:
        case_id, gold, expected = sentinel["case_id"], sentinel["gold"], sentinel["expected"]
        predictions = [p for p, _ in found.get(case_id, [])]
        if not predictions:
            reasons.append(f"case {case_id}: missing, the run did not finish it")
            sentinels.append({"case_id": case_id, "status": "missing"})
            continue
        if None in predictions:
            reasons.append(f"case {case_id}: unclassified, the conversation ended without a severity")
            sentinels.append({"case_id": case_id, "status": "unclassified"})
            continue
        differing = [p for p in predictions if p != expected]
        status = "ok" if not differing else "differs"
        sentinels.append({"case_id": case_id, "status": status, "now": predictions, "expected": expected})
        if not differing:
            continue
        if any(SEVERITY_RANK[p] < SEVERITY_RANK[gold] for p in differing) and gold == "emergent":
            reasons.append(f"case {case_id}: emergent case under-triaged as {', '.join(sorted(set(differing)))}")
        else:
            flips += 1
    if flips > MAX_NON_SAFETY_FLIPS:
        reasons.append(f"{flips} sentinels differ from the baseline answer (limit {MAX_NON_SAFETY_FLIPS})")
    watch = [
        {"case_id": w["case_id"], "gold": w["gold"], "baseline": w["observed"],
         "now": [p for p, _ in found.get(w["case_id"], [])]}
        for w in baseline["watch"]
    ]
    return GateResult(passed=not reasons, reasons=reasons, sentinels=sentinels, watch=watch)


def gate_command(checkpoint_path: str, baseline_path: str) -> int:
    with open(baseline_path) as f:
        baseline = json.load(f)
    with open(checkpoint_path) as f:
        rows = [json.loads(line) for line in f if line.strip()]
    result = evaluate_gate(rows, baseline)
    print(f"Eval gate ({baseline['leg']} leg, {baseline['variant']} set, {len(baseline['sentinels'])} sentinels): "
          f"{'PASS' if result.passed else 'FAIL'}")
    for sentinel in result.sentinels:
        print(f"  case {sentinel['case_id']}: {sentinel['status']}"
              + (f" (now {sentinel['now']}, expected {sentinel['expected']})" if sentinel["status"] == "differs" else ""))
    for reason in result.reasons:
        print(f"  - {reason}")
    if result.watch:
        print("Watch (known open cases, never fail the gate):")
        for watched in result.watch:
            print(f"  case {watched['case_id']} gold={watched['gold']} baseline={watched['baseline']} now={watched['now']}")
    return 0 if result.passed else 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Regression gate on the production path.")
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--baseline", required=True)
    args = parser.parse_args()
    sys.exit(gate_command(args.checkpoint, args.baseline))


if __name__ == "__main__":
    main()
