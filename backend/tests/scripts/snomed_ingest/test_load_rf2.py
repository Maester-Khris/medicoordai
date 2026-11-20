# backend/tests/scripts/snomed_ingest/test_load_rf2.py
import inspect
import os
import re
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../.."))

from scripts.snomed_ingest import load_rf2
from scripts.snomed_ingest.load_rf2 import select_subset_ids
from scripts.snomed_ingest.rf2_reader import DescriptionRow, RelationshipRow
from scripts.snomed_ingest.constants import CLINICAL_FINDING_ROOT, IS_A_TYPE_ID, FSN_TYPE_ID


def _rel(id_, source_id, destination_id):
    return RelationshipRow(id_, "20170731", True, "900000000000207008",
                            source_id, destination_id, "0", IS_A_TYPE_ID,
                            "900000000000011006", "900000000000451002")


def _desc(id_, concept_id, term):
    return DescriptionRow(id_, "20170731", True, "900000000000207008",
                           concept_id, "en", FSN_TYPE_ID, term, "900000000000448009")


def test_select_subset_ids_bounds_depth_and_restricts_to_clinical_finding():
    # SEED is a Clinical Finding descendant matched by keyword "cut". D1..D4 are
    # its descendants at depth 1-4 (must be included); D5 is depth 5 (must be
    # excluded — beyond MAX_SEED_DESCENDANT_DEPTH). PROC's FSN also matches "cut"
    # but it has no IS_A path to CLINICAL_FINDING_ROOT (e.g. a Procedure), so it
    # must be excluded by the Clinical-Finding-restriction, not just unmatched.
    relationships = [
        _rel("1", "SEED", CLINICAL_FINDING_ROOT),
        _rel("2", "D1", "SEED"),
        _rel("3", "D2", "D1"),
        _rel("4", "D3", "D2"),
        _rel("5", "D4", "D3"),
        _rel("6", "D5", "D4"),
    ]
    descriptions = [
        _desc("d1", "SEED", "Cut of hand (finding)"),
        _desc("d2", "PROC", "Wound cut repair (procedure)"),
    ]

    result = select_subset_ids(relationships, descriptions, keywords=["cut"])

    assert {"SEED", "D1", "D2", "D3", "D4"} <= result
    assert "D5" not in result
    assert "PROC" not in result


def test_select_subset_ids_unions_extra_seed_ids_not_matched_by_keywords():
    # ANCHOR is a Clinical Finding descendant with no FSN matching any keyword
    # (simulates a Task 2a anchor_mapping.py concept that Phase 1's keyword
    # matching never would have found on its own). AD1 is its depth-1
    # descendant (must be included via the same bounded-depth walk as any
    # other seed); UNRELATED is a separate Clinical Finding concept that
    # neither keywords nor extra_seed_ids reference (must stay excluded).
    relationships = [
        _rel("1", "ANCHOR", CLINICAL_FINDING_ROOT),
        _rel("2", "AD1", "ANCHOR"),
        _rel("3", "UNRELATED", CLINICAL_FINDING_ROOT),
    ]
    descriptions = [
        _desc("d1", "ANCHOR", "Some unrelated finding (finding)"),
        _desc("d2", "UNRELATED", "Another unrelated finding (finding)"),
    ]

    result = select_subset_ids(
        relationships, descriptions, keywords=["nomatch"], extra_seed_ids={"ANCHOR"},
    )

    assert {"ANCHOR", "AD1"} <= result
    assert "UNRELATED" not in result


def test_load_rf2_never_writes_layer_2_labels():
    # Structural isolation check (opposite direction of seed_red_flags.py's own
    # test_seed_red_flags_never_writes_layer_1_labels) — the whole-branch
    # review (CHANGELOG, 2026-08-03) flagged this as a load-bearing claim that
    # was never verified: Layer 1 (this module) must never be able to clobber
    # Layer 2 (RedFlag/FollowupQuestion/RedFlagCluster, seeded separately by
    # seed_red_flags.py). Scoped to load()'s own source, not the whole module,
    # so the module docstring's documented manual-wipe escape hatch
    # ("MATCH (n) DETACH DELETE n") doesn't produce a false positive here —
    # that's an explicit, separate, human-invoked operation, not part of the
    # automated ingestion path this test guards.
    source = inspect.getsource(load_rf2.load)

    forbidden_patterns = [
        r"MERGE\s*\([^)]*:RedFlagCluster",
        r"MERGE\s*\([^)]*:RedFlag\b",
        r"MERGE\s*\([^)]*:FollowupQuestion",
        r"CREATE\s*\([^)]*:RedFlagCluster",
        r"CREATE\s*\([^)]*:RedFlag\b",
        r"CREATE\s*\([^)]*:FollowupQuestion",
        r"SET\s+\w+\s*:\s*RedFlagCluster",
        r"SET\s+\w+\s*:\s*RedFlag\b",
        r"SET\s+\w+\s*:\s*FollowupQuestion",
        r"FOR\s*\([^)]*:RedFlagCluster",
        r"FOR\s*\([^)]*:RedFlag\b",
        r"FOR\s*\([^)]*:FollowupQuestion",
        r"-\[:HAS_RED_FLAG\]",
        r"-\[:ASKS\]",
        r"-\[:PART_OF\]",
        r"\bDELETE\b",
    ]
    for pattern in forbidden_patterns:
        assert not re.search(pattern, source), (
            f"load_rf2.load() must never write RedFlag/FollowupQuestion/"
            f"RedFlagCluster or their relationships, and must never DELETE -- "
            f"Layer 2 is seed_red_flags.py's exclusive write responsibility "
            f"(matched pattern: {pattern!r})"
        )

    # Positive control: load() must still genuinely write real Layer 1 data --
    # otherwise the assertions above would pass vacuously on an empty function.
    # The Cypher now lives in layer1_writer (load() delegates to it), so check both.
    from scripts.snomed_ingest import layer1_writer
    writers = inspect.getsource(layer1_writer)
    assert "write_concepts(" in source and "write_descriptions(" in source and "write_is_a(" in source
    assert "MERGE (c:SnomedConcept" in writers
    assert "MERGE (d:Description" in writers
    assert "MERGE (child)-[:IS_A]->(parent)" in writers
