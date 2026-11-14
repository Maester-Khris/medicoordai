import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from scripts.symptom_eval.ablation import CheckpointStore
from scripts.symptom_eval.compare_legs import compare_legs, format_comparison
from scripts.symptom_eval.confusion_matrix import ConfusionMatrixRow
from scripts.symptom_eval.domain import SEVERITY_RANK

NO_EXCLUSIONS = frozenset()


def _add(store, leg, case_id, repeat, predicted, gold="emergent", variant="original"):
    under = predicted is not None and SEVERITY_RANK[predicted] < SEVERITY_RANK[gold]
    row = ConfusionMatrixRow(case_id, predicted, gold, predicted == gold, under)
    store.append(variant, leg, repeat, row, None, None, [])


def _store(tmp_path):
    return CheckpointStore(str(tmp_path / "checkpoint.jsonl"))


def _fill(store, leg, outcomes_by_case):
    """outcomes_by_case: {case_id: [predicted per repeat]}"""
    for case_id, outcomes in outcomes_by_case.items():
        for repeat, predicted in enumerate(outcomes):
            _add(store, leg, case_id, repeat, predicted)


def test_per_vignette_rate_is_mean_over_repeats(tmp_path):
    store = _store(tmp_path)
    _fill(store, "off", {"1": ["urgent", "emergent"], "2": ["emergent", "emergent"]})
    _fill(store, "static", {"1": ["emergent", "emergent"], "2": ["emergent", "emergent"]})

    result = compare_legs(store, "original", "off", "static", NO_EXCLUSIONS, seed=1)

    assert result.under_triage.rate_a == pytest.approx(0.25)  # mean(0.5, 0.0)
    assert result.under_triage.rate_b == 0.0
    assert result.accuracy.rate_a == pytest.approx(0.75)


def test_mcnemar_tie_counts_as_under_triaged(tmp_path):
    store = _store(tmp_path)
    _fill(store, "off", {"1": ["urgent", "emergent"], "2": ["emergent", "emergent"]})
    _fill(store, "static", {"1": ["emergent", "emergent"], "2": ["emergent", "emergent"]})

    result = compare_legs(store, "original", "off", "static", NO_EXCLUSIONS, seed=1)

    assert (result.under_triage.mcnemar.only_a, result.under_triage.mcnemar.only_b) == (1, 0)
    assert result.accuracy.mcnemar is None


def test_excluded_cases_are_dropped_and_n_reported(tmp_path):
    store = _store(tmp_path)
    for leg in ("off", "static"):
        _fill(store, leg, {"1": ["emergent"], "2": ["emergent"], "3": ["urgent"]})

    result = compare_legs(store, "original", "off", "static", frozenset({"3"}), seed=1)

    assert result.n == 2
    assert result.under_triage.rate_a == 0.0  # the under-triaged case 3 was excluded


def test_only_intersection_of_vignettes_is_compared(tmp_path):
    store = _store(tmp_path)
    _fill(store, "off", {"1": ["emergent"], "2": ["emergent"], "3": ["emergent"]})
    _fill(store, "static", {"1": ["emergent"], "2": ["emergent"]})

    assert compare_legs(store, "original", "off", "static", NO_EXCLUSIONS, seed=1).n == 2


def test_fewer_than_two_shared_vignettes_raises(tmp_path):
    store = _store(tmp_path)
    _fill(store, "off", {"1": ["emergent"], "2": ["emergent"]})
    _fill(store, "static", {"2": ["emergent"], "3": ["emergent"]})

    with pytest.raises(ValueError, match="at least 2"):
        compare_legs(store, "original", "off", "static", NO_EXCLUSIONS, seed=1)


def test_unclassified_counted_separately_and_not_under_triaged(tmp_path):
    store = _store(tmp_path)
    _fill(store, "off", {"1": ["emergent"], "2": [None]})
    _fill(store, "static", {"1": ["emergent"], "2": ["emergent"]})

    result = compare_legs(store, "original", "off", "static", NO_EXCLUSIONS, seed=1)

    assert result.unclassified_a == 1
    assert result.unclassified_b == 0
    assert result.under_triage.rate_a == 0.0
    assert result.accuracy.rate_a == 0.5


def test_other_variant_is_not_mixed_in(tmp_path):
    store = _store(tmp_path)
    for leg in ("off", "static"):
        _fill(store, leg, {"1": ["emergent"], "2": ["emergent"]})
    _add(store, "off", "9", 0, "routine", variant="lay")

    assert compare_legs(store, "original", "off", "static", NO_EXCLUSIONS, seed=1).n == 2


def test_format_comparison_states_n_rates_interval_and_counts(tmp_path):
    store = _store(tmp_path)
    _fill(store, "off", {"1": ["urgent"], "2": [None], "3": ["emergent"]})
    _fill(store, "static", {"1": ["emergent"], "2": ["emergent"], "3": ["emergent"]})

    text = format_comparison(compare_legs(store, "original", "off", "static", NO_EXCLUSIONS, seed=1))

    for expected in ("n=3", "off", "static", "95%", "McNemar", "unclassified"):
        assert expected in text
