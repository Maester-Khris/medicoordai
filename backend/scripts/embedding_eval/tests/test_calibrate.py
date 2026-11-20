import json
import os
from pathlib import Path

import pytest

os.environ.setdefault("OPENAI_API_KEY", "test")

from scripts.embedding_eval.calibrate import (  # noqa: E402
    CATEGORIES,
    calibrate_thresholds,
    load_negative_set,
    split_negative_set,
)

NEGATIVES = Path(__file__).resolve().parent.parent / "data" / "negative_queries.json"


def _accepted(pairs: list[tuple[float, float]], threshold: float, margin: float) -> float:
    return sum(1 for top, gap in pairs if top >= threshold and gap >= margin) / len(pairs)


def test_calibration_meets_false_match_target_on_separable_data() -> None:
    in_scope = [(0.80 + i * 0.01, 0.10 + i * 0.005) for i in range(20)]
    out_of_scope = [(0.30 + i * 0.01, 0.01 + i * 0.002) for i in range(20)]
    result = calibrate_thresholds(in_scope, out_of_scope, target_false_match=0.05)
    assert result.false_match <= 0.05
    assert result.in_scope_retained == 1.0
    assert _accepted(out_of_scope, result.threshold, result.margin) == result.false_match


def test_calibration_returns_most_permissive_pair_meeting_the_target() -> None:
    in_scope = [(0.9, 0.3), (0.8, 0.3), (0.7, 0.3), (0.6, 0.3)]
    out_of_scope = [(0.65, 0.3), (0.2, 0.0), (0.1, 0.0), (0.1, 0.0)]
    # target 0.25 allows the one out-of-scope item at 0.65, which admits all four in-scope items.
    loose = calibrate_thresholds(in_scope, out_of_scope, target_false_match=0.25)
    assert loose.in_scope_retained == 1.0
    assert loose.false_match == 0.25
    # target 0.0 forces the threshold above 0.65, keeping three in-scope items (0.9, 0.8, 0.7).
    strict = calibrate_thresholds(in_scope, out_of_scope, target_false_match=0.0)
    assert strict.false_match == 0.0
    assert strict.in_scope_retained == 0.75


def test_unsatisfiable_target_returns_the_strictest_pair_and_reports_actual_false_match() -> None:
    same = [(0.8, 0.2), (0.8, 0.2), (0.6, 0.1), (0.6, 0.1)]
    result = calibrate_thresholds(same, same, target_false_match=0.0)
    # No observed pair separates the sets; the strictest accepts the fewest out-of-scope items.
    assert result.false_match == 0.5
    assert result.in_scope_retained == 0.5
    assert result.threshold == 0.8


def test_empty_inputs_do_not_crash() -> None:
    nothing = calibrate_thresholds([], [])
    assert (nothing.threshold, nothing.margin) == (1.0, 0.0)
    assert (nothing.in_scope_retained, nothing.false_match) == (0.0, 0.0)
    only_in = calibrate_thresholds([(0.7, 0.2)], [])
    assert only_in.in_scope_retained == 1.0 and only_in.false_match == 0.0


def test_split_is_deterministic_for_a_seed() -> None:
    items = [{"text": f"m{i}", "category": CATEGORIES[i % 6]} for i in range(60)]
    first = split_negative_set(items, seed=7)
    assert first == split_negative_set(items, seed=7)
    validation, test = first
    assert len(validation) == len(test) == 30
    assert {i["text"] for i in validation}.isdisjoint(i["text"] for i in test)
    for category in CATEGORIES:
        assert sum(1 for i in validation if i["category"] == category) == 5
    assert first != split_negative_set(items, seed=8)


def test_negative_queries_file_is_valid() -> None:
    items = load_negative_set(NEGATIVES)
    assert len(items) == 120
    for category in CATEGORIES:
        assert sum(1 for i in items if i["category"] == category) == 20


def test_load_rejects_bad_files(tmp_path: Path) -> None:
    def write(payload: dict) -> Path:
        path = tmp_path / "n.json"
        path.write_text(json.dumps(payload))
        return path

    ok = {"text": "hello there", "category": CATEGORIES[0]}
    with pytest.raises(ValueError):
        load_negative_set(write({"version": 2, "items": [ok]}))
    with pytest.raises(ValueError):
        load_negative_set(write({"version": 1, "items": [{"text": " ", "category": CATEGORIES[0]}]}))
    with pytest.raises(ValueError):
        load_negative_set(write({"version": 1, "items": [{"text": "x", "category": "other"}]}))
    with pytest.raises(ValueError):
        load_negative_set(write({"version": 1, "items": [ok, {**ok, "text": "HELLO there"}]}))
