"""Abstention threshold calibration and the negative query set (spec 8.5). Pure: no torch, no network.

A message is accepted iff top >= threshold and gap >= margin, the same rule as graph/semantic/abstention.decide.
Each score pair is (top anchor score, gap to the second anchor score).
"""
import json
import random
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

CATEGORIES: tuple[str, ...] = (
    "off_topic_chat",
    "health_admin",
    "outside_anchor_symptoms",
    "near_miss",
    "empty_or_very_short",
    "injection_style",
)
NEGATIVE_SET_VERSION = 1


@dataclass(frozen=True)
class Thresholds:
    threshold: float
    margin: float
    in_scope_retained: float
    false_match: float


def _accept_rate(pairs: Sequence[tuple[float, float]], threshold: float, margin: float) -> float:
    if not pairs:
        return 0.0
    return sum(1 for top, gap in pairs if top >= threshold and gap >= margin) / len(pairs)


def calibrate_thresholds(
    in_scope: Sequence[tuple[float, float]],
    out_of_scope: Sequence[tuple[float, float]],
    target_false_match: float = 0.05,
) -> Thresholds:
    """Pick (threshold, margin) maximising in-scope retention with false match <= target.

    Candidates are the observed top scores and gaps (plus 0.0 for the margin). Ties go to the lower false
    match, then the higher threshold, then the higher margin. If no pair meets the target, the strictest
    pair (lowest false match, ties by highest retention) is returned with its actual false match.
    With no scores at all it returns Thresholds(1.0, 0.0, 0.0, 0.0), which accepts nothing.
    """
    all_pairs = [*in_scope, *out_of_scope]
    if not all_pairs:
        return Thresholds(1.0, 0.0, 0.0, 0.0)
    thresholds = sorted({top for top, _ in all_pairs})
    margins = sorted({0.0, *(gap for _, gap in all_pairs)})
    best_ok: tuple[float, float, float, float] | None = None
    best_strict: tuple[float, float, float, float] | None = None
    for t in thresholds:
        for m in margins:
            retained = _accept_rate(in_scope, t, m)
            false_match = _accept_rate(out_of_scope, t, m)
            if false_match <= target_false_match:
                key = (retained, -false_match, t, m)
                if best_ok is None or key > (best_ok[2], -best_ok[3], best_ok[0], best_ok[1]):
                    best_ok = (t, m, retained, false_match)
            skey = (-false_match, retained, t, m)
            if best_strict is None or skey > (-best_strict[3], best_strict[2], best_strict[0], best_strict[1]):
                best_strict = (t, m, retained, false_match)
    chosen = best_ok or best_strict
    assert chosen is not None
    return Thresholds(*chosen)


def split_negative_set(items: Sequence[dict], seed: int) -> tuple[list[dict], list[dict]]:
    """Deterministic 50/50 validation/test split, stratified by category."""
    rng = random.Random(seed)
    by_category: dict[str, list[dict]] = defaultdict(list)
    for item in items:
        by_category[item["category"]].append(item)
    validation: list[dict] = []
    test: list[dict] = []
    for category in sorted(by_category):
        group = list(by_category[category])
        rng.shuffle(group)
        half = (len(group) + 1) // 2
        validation.extend(group[:half])
        test.extend(group[half:])
    return validation, test


def load_negative_set(path: Path) -> list[dict]:
    """Load and validate the negative query set; raise ValueError on any problem."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("version") != NEGATIVE_SET_VERSION:
        raise ValueError(f"unsupported negative set version {data.get('version')!r}")
    items: list[dict] = data.get("items", [])
    seen: set[str] = set()
    for i, item in enumerate(items):
        text = item.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ValueError(f"item {i} has empty text")
        if item.get("category") not in CATEGORIES:
            raise ValueError(f"item {i} has unknown category {item.get('category')!r}")
        key = text.strip().lower()
        if key in seen:
            raise ValueError(f"duplicate text {text!r}")
        seen.add(key)
    return items
