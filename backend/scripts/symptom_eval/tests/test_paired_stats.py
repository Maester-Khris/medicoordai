import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from scripts.symptom_eval.paired_stats import mcnemar_exact, paired_bootstrap_diff


def test_mcnemar_7_vs_1_is_0_0703125():
    a = [True] * 7 + [False]
    b = [False] * 7 + [True]

    result = mcnemar_exact(a, b)

    assert (result.only_a, result.only_b) == (7, 1)
    assert result.p_value == 0.0703125


def test_mcnemar_zero_discordant_is_one():
    result = mcnemar_exact([True, False, True], [True, False, True])

    assert (result.only_a, result.only_b) == (0, 0)
    assert result.p_value == 1.0


def test_mcnemar_counts_ignore_concordant_pairs():
    result = mcnemar_exact([True, True, False, False], [True, False, False, True])

    assert (result.only_a, result.only_b) == (1, 1)
    assert result.p_value == 1.0


def test_bootstrap_known_difference():
    result = paired_bootstrap_diff([1.0] * 5, [0.0] * 5, seed=1)

    assert result.diff == 1.0
    assert result.low == result.high == 1.0


def test_bootstrap_identical_vectors_zero_width():
    result = paired_bootstrap_diff([0.0, 1.0, 0.5], [0.0, 1.0, 0.5], seed=1)

    assert result.diff == 0.0
    assert result.low == result.high == 0.0


def test_bootstrap_reproducible_with_seed_and_interval_brackets_diff():
    a = [1.0, 0.0, 1.0, 1.0, 0.0, 1.0, 0.5, 0.0]
    b = [0.0, 0.0, 1.0, 0.0, 0.0, 1.0, 0.0, 0.0]

    first = paired_bootstrap_diff(a, b, seed=7)
    second = paired_bootstrap_diff(a, b, seed=7)

    assert first == second
    assert first.seed == 7 and first.resamples == 10_000
    assert first.low <= first.diff <= first.high


@pytest.mark.parametrize("a, b", [([], []), ([True, False], [True]), ([True], [False])])
def test_mcnemar_raises_on_empty_unequal_or_single_pair(a, b):
    with pytest.raises(ValueError):
        mcnemar_exact(a, b)


@pytest.mark.parametrize("a, b", [([], []), ([1.0, 0.0], [1.0]), ([1.0], [0.0])])
def test_bootstrap_raises_on_empty_unequal_or_single_pair(a, b):
    with pytest.raises(ValueError):
        paired_bootstrap_diff(a, b, seed=1)
