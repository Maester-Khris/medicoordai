from scripts.snomed_ingest.anchor_selection import (
    BLOCKED_ROOTS,
    CATCH_ALL_NAMES,
    DEFAULT_INDEX_DEPTH,
    AnchorSpec,
    assign_concepts,
    resolve_index_depth,
)


def test_concept_goes_to_nearest_anchor():
    children = {"A": ["a1"], "a1": ["a2"], "B": ["a2"]}
    anchors = [AnchorSpec("A", "a", 2), AnchorSpec("B", "b", 2)]
    result = assign_concepts(children, anchors)
    assert result.concept_anchor["a2"] == "B"  # 1 step from B, 2 from A
    assert result.concept_anchor["a1"] == "A"
    assert result.concept_depth["a2"] == 1
    assert result.concept_anchor["A"] == "A" and result.concept_depth["A"] == 0


def test_tie_goes_to_earlier_anchor_and_is_reported_in_ties():
    children = {"A": ["x"], "B": ["x"]}
    anchors = [AnchorSpec("A", "a", 1), AnchorSpec("B", "b", 1)]
    result = assign_concepts(children, anchors)
    assert result.concept_anchor["x"] == "A"
    assert result.ties["x"] == ("A", "B")


def test_depth_zero_returns_only_the_anchor():
    children = {"A": ["x", "y"]}
    result = assign_concepts(children, [AnchorSpec("A", "a", 0)])
    assert result.concept_anchor == {"A": "A"}


def test_blocked_root_is_never_assigned_or_traversed():
    blocked = next(iter(BLOCKED_ROOTS))
    children = {"A": [blocked, "ok"], blocked: ["under_blocked"]}
    result = assign_concepts(children, [AnchorSpec("A", "a", 3)])
    assert blocked not in result.concept_anchor
    assert "under_blocked" not in result.concept_anchor
    assert "ok" in result.concept_anchor


def test_anchor_over_200_concepts_at_depth_two_is_flagged_broad():
    children = {"A": [f"c{i}" for i in range(201)], "B": ["b1"]}
    anchors = [AnchorSpec("A", "a", 0), AnchorSpec("B", "b", 0)]
    result = assign_concepts(children, anchors)
    # broad is measured at depth 2 even though depth 0 is applied
    assert result.broad == ("A",)
    assert result.concept_anchor == {"A": "A", "B": "B"}


def test_catch_all_names_default_to_depth_zero():
    for name in CATCH_ALL_NAMES:
        assert resolve_index_depth(name, "1", {}) == 0
    assert resolve_index_depth("Headache", "1", {}) == DEFAULT_INDEX_DEPTH == 1


def test_override_beats_default():
    assert resolve_index_depth("Headache", "7", {"7": 2}) == 2
    assert resolve_index_depth(CATCH_ALL_NAMES[0], "7", {"7": 1}) == 1
