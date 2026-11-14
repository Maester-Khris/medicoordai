# backend/scripts/snomed_ingest/load_rf2.py
"""
Phase 1 Layer 1 ingestion: SNOMED CT Canadian Edition RF2 Snapshot -> Neo4j.

Loads Concept, Description, and IS_A Relationship rows for a complaint-anchored
subset (see select_subset_ids() below and task-1-report.md for the full
rationale — this replaces the original plan's single-root full-Clinical-Finding
subtree design, which was ~3x over Neo4j AuraDB Free tier's 200,000-node cap).

Seeds from both keyword matches and Task 2a's final anchor list, so the loaded
subset and the anchor mapping can't silently diverge again (see task-2c-report.md).

Standalone script only — never imported by the request path
(backend/services/llm_agent.py, backend/graph/*). Invoke as:
    cd backend && python -m scripts.snomed_ingest.load_rf2 --rf2-snapshot-dir ... --source-release ... --neo4j-uri ... --neo4j-user ... --neo4j-password ...

Note on reruns: all writes are MERGE-on-id (idempotent — safe to rerun with the
*same* seed/complaint inputs). But if a rerun changes the seed set (e.g. the
complaint list or keyword-matching logic changes), MERGE never deletes nodes
that fall out of the new subset — they're left behind as orphans. Rerunning
with a different scope requires manually wiping first (MATCH (n) DETACH DELETE n
or equivalent) if a clean, exactly-matching graph is required.
"""
import argparse
from pathlib import Path
from typing import Iterable
from neo4j import GraphDatabase

from scripts.snomed_ingest.constants import (
    CLINICAL_FINDING_ROOT, IS_A_TYPE_ID, FSN_TYPE_ID, MAX_SEED_DESCENDANT_DEPTH,
)
from scripts.snomed_ingest.rf2_reader import (
    read_concepts, read_descriptions, read_relationships,
    DescriptionRow, RelationshipRow,
)
from scripts.snomed_ingest.complaint_seeds import (
    load_complaint_keywords, find_seed_concept_ids,
)
from scripts.snomed_ingest.layer1_writer import (
    write_concepts,
    write_constraints,
    write_descriptions,
    write_is_a,
)
from graph.snomed_neo4j.anchor_mapping import ANCHOR_MAPPINGS

# Resolved relative to this file rather than cwd, so it's correct regardless of the
# invocation directory (invoked as `python -m scripts.snomed_ingest.load_rf2` from
# backend/, per the module docstring, but not assumed here).
DEFAULT_COMPLAINTS_PATH = Path(__file__).resolve().parents[2] / "triage/resources/symptom_triage_data.json"


def concept_ids_in_subset(
    relationships: Iterable[RelationshipRow],
    root: str | Iterable[str],
    max_depth: int | None = None,
) -> set[str]:
    """Every concept reachable from `root` by walking IS_A edges downward
    (i.e. every descendant of root, transitively), plus root itself.

    `root` may be a single concept id (str) or an iterable of seed concept ids —
    the multi-seed form supports the complaint-anchored subset (see
    complaint_seeds.py): union the descendants of every CTAS complaint's seed
    concepts instead of walking one root's entire subtree.

    `max_depth` bounds how many IS_A hops to descend from each root/seed;
    None (default) walks the full subtree, preserving the original single-root
    behavior this function was written for.

    Note: `relationships` is iterated in full to build the children_of index;
    pass a re-iterable collection (e.g. list), not a one-shot generator, if
    calling this more than once with the same relationships.
    """
    roots = {root} if isinstance(root, str) else set(root)
    children_of: dict[str, list[str]] = {}
    for r in relationships:
        if r.type_id == IS_A_TYPE_ID and r.active:
            children_of.setdefault(r.destination_id, []).append(r.source_id)

    subset = set(roots)
    frontier = list(roots)
    depth = 0
    while frontier and (max_depth is None or depth < max_depth):
        next_frontier = []
        for parent in frontier:
            for child in children_of.get(parent, []):
                if child not in subset:
                    subset.add(child)
                    next_frontier.append(child)
        frontier = next_frontier
        depth += 1
    return subset


def select_subset_ids(
    relationships: Iterable[RelationshipRow],
    descriptions: Iterable[DescriptionRow],
    keywords: list[str],
    extra_seed_ids: Iterable[str] = (),
) -> set[str]:
    """The complaint-anchored subset-selection rule (see module docstring):
    match complaint keywords against FSNs restricted to genuine Clinical
    Finding descendants (fixes a false-positive-seed problem — unrestricted
    keyword matching also hits Procedure/Body Structure/other non-finding
    concepts by string coincidence, e.g. "shock" matching "Electric shock
    therapy"), union in `extra_seed_ids` (e.g. Task 2a's anchor_mapping.py
    concept IDs — see module docstring), then union each seed's IS_A
    descendants up to MAX_SEED_DESCENDANT_DEPTH.

    `extra_seed_ids` is run through the same Clinical-Finding restriction as
    the keyword-matched seeds even though Task 2a's anchors are already
    guaranteed Clinical Finding concepts by construction — harmless, and
    keeps this function's invariant (every seed is Clinical-Finding-restricted)
    simple and uniform regardless of seed source.

    Extracted from load() so it's testable without a live Neo4j driver.

    Note: `relationships` is traversed twice internally (once to compute the
    Clinical Finding subtree, once for the final seed-descendant walk) — pass
    a re-iterable collection (e.g. list), not a one-shot generator.
    """
    clinical_finding_subtree = concept_ids_in_subset(relationships, CLINICAL_FINDING_ROOT)
    seed_ids = (find_seed_concept_ids(descriptions, keywords) | set(extra_seed_ids)) & clinical_finding_subtree
    return concept_ids_in_subset(relationships, seed_ids, max_depth=MAX_SEED_DESCENDANT_DEPTH)


def load(
    rf2_snapshot_dir: Path,
    source_release: str,
    neo4j_uri: str,
    neo4j_auth: tuple[str, str],
    complaints_path: Path = DEFAULT_COMPLAINTS_PATH,
) -> None:
    terminology = rf2_snapshot_dir / "Terminology"
    concept_file = next(terminology.glob("sct2_Concept_Snapshot_*.txt"))
    description_file = next(terminology.glob("sct2_Description_Snapshot_*.txt"))
    relationship_file = next(terminology.glob("sct2_Relationship_Snapshot_*.txt"))

    relationships = list(read_relationships(relationship_file))
    descriptions = list(read_descriptions(description_file))

    keywords = load_complaint_keywords(complaints_path)
    anchor_seed_ids = {m.anchor_concept_id for m in ANCHOR_MAPPINGS}
    subset_ids = select_subset_ids(relationships, descriptions, keywords, anchor_seed_ids)

    driver = GraphDatabase.driver(neo4j_uri, auth=neo4j_auth)
    with driver.session() as session:
        write_constraints(session)

        concept_rows = (
            {"id": c.id, "source_release": source_release, "effective_time": c.effective_time}
            for c in read_concepts(concept_file)
            if c.id in subset_ids and c.active
        )
        write_concepts(session, concept_rows)

        # `descriptions` was already read fully into memory above for seed matching;
        # reuse it here instead of re-reading the file a second time. Loads both
        # EN and FR descriptions (and all description types, not just FSN) for the
        # scoped subset — synonyms matter for Phase 2's later matching.
        description_rows = (
            {
                "concept_id": d.concept_id, "id": d.id, "term": d.term,
                "language_code": d.language_code, "is_fsn": d.type_id == FSN_TYPE_ID,
                "source_release": source_release, "effective_time": d.effective_time,
            }
            for d in descriptions
            if d.concept_id in subset_ids and d.active
        )
        write_descriptions(session, description_rows)

        is_a_rows = (
            {"source_id": rel.source_id, "destination_id": rel.destination_id}
            for rel in relationships
            if (rel.type_id == IS_A_TYPE_ID and rel.active
                and rel.source_id in subset_ids and rel.destination_id in subset_ids)
        )
        write_is_a(session, is_a_rows)
    driver.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--rf2-snapshot-dir", type=Path, required=True)
    parser.add_argument("--source-release", required=True)
    parser.add_argument("--neo4j-uri", required=True)
    parser.add_argument("--neo4j-user", required=True)
    parser.add_argument("--neo4j-password", required=True)
    parser.add_argument("--complaints-path", type=Path, default=DEFAULT_COMPLAINTS_PATH)
    args = parser.parse_args()
    load(args.rf2_snapshot_dir, args.source_release, args.neo4j_uri,
         (args.neo4j_user, args.neo4j_password), args.complaints_path)
