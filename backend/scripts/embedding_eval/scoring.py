"""Pure scoring helpers for the embedding retrieval experiment: no torch, no I/O."""
import math

import numpy as np

TOP_K_MEAN = 3


def anchor_scores(sims: np.ndarray, target_anchor: np.ndarray, n_anchors: int, agg: str = "max") -> np.ndarray:
    """One score per anchor from the similarity of one query to every target string.

    agg="max": best target per anchor. agg="top3mean": mean of the best three, which dampens
    anchors that win only by owning thousands of targets.
    """
    scores = np.full(n_anchors, -1.0)
    if agg == "max":
        np.maximum.at(scores, target_anchor, sims)
        return scores
    if agg == "top3mean":
        for anchor in np.unique(target_anchor):
            best = np.sort(sims[target_anchor == anchor])[-TOP_K_MEAN:]
            scores[anchor] = best.mean()
        return scores
    raise ValueError(f"unknown aggregation {agg!r}")


def rank_of(scores: np.ndarray, gold: int) -> int:
    """1-based rank of the gold anchor; ties do not count against it."""
    return int((scores > scores[gold]).sum()) + 1


def wilson(hits: int, n: int, z: float = 1.96) -> tuple[int, int]:
    """95% Wilson interval for a hit rate, as whole percentages."""
    p = hits / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return round(max(0.0, centre - half) * 100), round(min(1.0, centre + half) * 100)


def summarise(ranks: list[int], neutral: list[bool]) -> dict:
    """hit@k, MRR and a hit@5 interval over all queries and over the vocabulary-neutral subset."""
    out: dict = {}
    for name, keep in (("all", [True] * len(ranks)), ("neutral", neutral)):
        r = np.array([rank for rank, k in zip(ranks, keep) if k])
        if len(r) == 0:
            continue
        out[name] = {
            "n": int(len(r)),
            **{f"hit@{k}": int((r <= k).sum()) for k in (1, 3, 5, 10)},
            "mrr": round(float((1 / r).mean()), 3),
            "hit@5_ci95": wilson(int((r <= 5).sum()), len(r)),
        }
    return out
