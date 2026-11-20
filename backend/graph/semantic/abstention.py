"""Abstention: decide whether the semantic candidates are trustworthy enough to use.

Semantic search always returns *something*, even for a message that matches no complaint. Two conditions
guard against that: the best anchor must score at least `threshold`, and (when a second anchor exists) it must
beat the runner-up by `margin`, so a message that is equally close to two complaints is not forced onto one.
Both numbers come from calibration against the negative query set, not from guesswork.
"""
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from graph.semantic.candidates import Candidate


@dataclass(frozen=True)
class Decision:
    accepted: bool
    reason: str  # ok | low_score | small_gap | no_candidates


def anchor_scores(candidates: Sequence[Candidate]) -> dict[str, float]:
    """Best score per anchor: several phrasings of one complaint count once, as their strongest."""
    scores: dict[str, float] = {}
    for c in candidates:
        scores[c.anchor_id] = max(c.score, scores.get(c.anchor_id, c.score))
    return scores


def decide(scores: Mapping[str, float], threshold: float, margin: float) -> Decision:
    if not scores:
        return Decision(False, "no_candidates")
    ranked = sorted(scores.values(), reverse=True)
    if ranked[0] < threshold:
        return Decision(False, "low_score")
    if len(ranked) > 1 and ranked[0] - ranked[1] < margin:
        return Decision(False, "small_gap")
    return Decision(True, "ok")
