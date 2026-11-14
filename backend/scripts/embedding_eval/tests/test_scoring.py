import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from scripts.embedding_eval.scoring import anchor_scores, rank_of, summarise, wilson

TARGET_ANCHOR = np.array([0, 0, 1, 1, 2])


def test_max_aggregation_takes_the_best_target_per_anchor():
    sims = np.array([0.1, 0.9, 0.5, 0.4, 0.2])
    assert anchor_scores(sims, TARGET_ANCHOR, 3).tolist() == [0.9, 0.5, 0.2]


def test_top3mean_dampens_an_anchor_that_wins_by_one_lucky_target():
    sims = np.array([0.9, 0.1, 0.6, 0.6, 0.2])
    by_max = anchor_scores(sims, TARGET_ANCHOR, 3, "max")
    by_mean = anchor_scores(sims, TARGET_ANCHOR, 3, "top3mean")
    assert rank_of(by_max, 1) == 2 and rank_of(by_mean, 1) == 1


def test_rank_of_does_not_penalise_ties_and_is_one_based():
    assert rank_of(np.array([0.5, 0.5, 0.1]), 1) == 1
    assert rank_of(np.array([0.9, 0.5, 0.1]), 2) == 3


def test_unknown_aggregation_raises():
    with pytest.raises(ValueError):
        anchor_scores(np.zeros(5), TARGET_ANCHOR, 3, "median")


def test_summarise_counts_hits_and_splits_the_neutral_subset():
    s = summarise([1, 4, 12], [True, False, True])
    assert s["all"]["hit@1"] == 1 and s["all"]["hit@5"] == 2 and s["all"]["hit@10"] == 2
    assert s["neutral"]["n"] == 2 and s["neutral"]["hit@5"] == 1


def test_wilson_interval_brackets_the_rate():
    low, high = wilson(80, 100)
    assert low < 80 < high
