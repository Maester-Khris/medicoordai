# backend/scripts/snomed_ingest/seed_red_flags.py
"""
Phase 2 Layer 2 ingestion: red-flag overlay from anchor_mapping.py -> Neo4j.

For each (ctas_alias -> anchor_concept_id) mapping in anchor_mapping.ANCHOR_MAPPINGS,
reads that complaint's red_flags from symptom_triage_data.json and writes RedFlag +
FollowupQuestion nodes, and HAS_RED_FLAG/ASKS edges, anchored to the already-loaded
SnomedConcept node for that anchor.

Structurally cannot touch :SnomedConcept/:Description (Layer 1) -- every Cypher
statement in this module that references those labels is MATCH-only, never
MERGE/SET/CREATE. Layer 1 is load_rf2.py's exclusive write responsibility; this
module is Layer 2's, and the two must never overlap (see
test_seed_red_flags.py::test_seed_red_flags_never_writes_layer_1_labels, which
enforces this structurally by inspecting this module's own source).

Standalone script only -- never imported by the request path
(backend/services/llm_agent.py, backend/graph/*). Invoke as:
    cd backend && python -m scripts.snomed_ingest.seed_red_flags --neo4j-uri ... --neo4j-user ... --neo4j-password ...

Note on reruns: all writes are MERGE-on-key -- idempotent, safe to rerun.
RedFlag is keyed by (anchor_id, indicator), not indicator text alone (I-1/I-2
fix, 2026-08): an indicator like "Shock" recurs across many complaints/anchors,
but each anchor now gets its OWN RedFlag node for it, so a cluster edge on one
anchor's node can never leak into an unrelated anchor, and each anchor keeps
its own ASKS->FollowupQuestion edge instead of racing other anchors for a
shared node's arbitrarily-ordered edges. FollowupQuestion is now keyed by
(anchor_id, text) too (graph v3): a question node shared across anchors would
make every anchor's traversal reach questions meant for other complaints, and
makes per-anchor review and deletion impossible. The same wording on two
anchors is therefore two nodes.

Known limitation (not fixed here, flagged per this repo's convention): Phase 1
(load_rf2.py) loads a keyword-seeded Clinical Finding subset, bounded to stay under
Neo4j AuraDB Free tier's 200,000-node cap. anchor_mapping.py's 154 anchors were
chosen against the FULL SNOMED terminology (via search_snomed.py), independently of
what Phase 1 actually loaded. Where an anchor_concept_id isn't present as a
SnomedConcept node in the live graph, this script's MATCH silently matches zero
rows for that complaint -- no error, no red flags written for it. This is correct
behavior given the MATCH-only constraint (this script must never MERGE/CREATE a
SnomedConcept node just to attach red flags to it), but it does mean actual
Layer 2 coverage can be materially smaller than the 154-mapping input set. Rerunning
this script after Phase 1's subset is expanded will backfill the gap with no
cleanup needed, since all writes here are idempotent.
"""
import argparse
import json
from itertools import islice
from pathlib import Path
from typing import Any, Iterable, Iterator, TypeVar

from neo4j import GraphDatabase, Session

from graph.snomed_neo4j.anchor_mapping import ANCHOR_MAPPINGS, AnchorMapping

# Resolved relative to this file rather than cwd, matching load_rf2.py's
# DEFAULT_COMPLAINTS_PATH convention -- correct regardless of invocation directory.
DEFAULT_COMPLAINTS_PATH = Path(__file__).resolve().parents[2] / "triage/resources/symptom_triage_data.json"

# Batch size for UNWIND-based writes. The write volume here (low hundreds of
# red-flag rows, not Phase 1's tens of thousands) doesn't require batching for
# performance the way Phase 1 did, but the same discipline is applied from the
# start per this pipeline's established convention: fewer round-trips, and a
# batch size small enough that the required per-batch progress logging (below)
# is actually meaningful rather than a single "[1/1] (100%)" line.
BATCH_SIZE = 50

# Pilot RedFlagCluster (I9) — deliberately narrow scope, see plan
# 2026-08-03-sprint19-postreview-critical-important-fixes.md, Task 5. Grounds
# design §4 point 3's cross-symptom mechanism in the same three anchors
# already used by the Phase 6 Step 2 worked example
# (test_two_turn_eval.py / research artifact Addendum 3). Expanding cluster
# coverage beyond this pilot needs the same clinical-review rigor as Task 2a
# — not done here.
PILOT_CLUSTERS = [
    {
        "cluster_name": "Cardiac symptom cluster",
        "anchor_concept_ids": ["426396005", "267036007", "271594007"],
    },
]

def seed_pilot_clusters(session) -> None:
    for cluster in PILOT_CLUSTERS:
        session.run(
            "MERGE (cluster:RedFlagCluster {name: $cluster_name})",
            {"cluster_name": cluster["cluster_name"]},
        )
        session.run(
            "MATCH (anchor:SnomedConcept)-[:HAS_RED_FLAG]->(rf:RedFlag) "
            "WHERE anchor.id IN $anchor_concept_ids "
            "MATCH (cluster:RedFlagCluster {name: $cluster_name}) "
            "MERGE (rf)-[:PART_OF]->(cluster)",
            {
                "anchor_concept_ids": cluster["anchor_concept_ids"],
                "cluster_name": cluster["cluster_name"],
            },
        )

T = TypeVar("T")


def _batched(iterable: Iterable[T], size: int) -> Iterator[list[T]]:
    it = iter(iterable)
    while batch := list(islice(it, size)):
        yield batch


def load_red_flag_lookup(complaints_path: Path = DEFAULT_COMPLAINTS_PATH) -> dict[str, list[dict[str, Any]]]:
    """Read symptom_triage_data.json directly (no load_red_flag_content() helper
    exists on static_provider.py) and build a {complaint name: red_flags list}
    lookup once. Keys match ANCHOR_MAPPINGS[*].ctas_alias by exact string equality
    (already verified 1:1 by a prior review -- no fuzzy matching)."""
    complaints = json.loads(complaints_path.read_text())
    return {complaint["name"]: complaint["red_flags"] for complaint in complaints}


def build_rows(
    mappings: list[AnchorMapping],
    red_flag_lookup: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Flatten (mapping, red_flag) pairs into one row per red flag, ready for
    UNWIND. Extracted from seed() so it's testable without a live Neo4j driver
    (Clean Code: test business rules without a DB).

    Each red flag has exactly one followup_question string (not a list called
    "followups" -- that's a bug in the plan document's original pseudocode), so
    this produces exactly one row per red flag, not one row per (red flag, question)
    pair.
    """
    rows: list[dict[str, Any]] = []
    for mapping in mappings:
        for red_flag in red_flag_lookup.get(mapping.ctas_alias, []):
            rows.append(
                {
                    "anchor_id": mapping.anchor_concept_id,
                    "indicator": red_flag["indicator"],
                    "ctas_level": red_flag["ctas_level"],
                    "app_severity": red_flag["app_severity"],
                    "followup_question": red_flag["followup_question"],
                }
            )
    return rows


def _count_layer_2(session: Session) -> dict[str, int]:
    """Read-only current-state counts for the four things this script writes.
    Used both for the script's own final summary and for idempotency verification
    (rerun and confirm identical counts)."""
    counts: dict[str, int] = {}
    for key, query in (
        ("RedFlag", "MATCH (n:RedFlag) RETURN count(n) AS n"),
        ("FollowupQuestion", "MATCH (n:FollowupQuestion) RETURN count(n) AS n"),
        ("HAS_RED_FLAG", "MATCH ()-[r:HAS_RED_FLAG]->() RETURN count(r) AS n"),
        ("ASKS", "MATCH ()-[r:ASKS]->() RETURN count(r) AS n"),
    ):
        counts[key] = session.run(query).single()["n"]
    return counts


def seed(
    neo4j_uri: str,
    neo4j_auth: tuple[str, str],
    complaints_path: Path = DEFAULT_COMPLAINTS_PATH,
    do_seed_pilot_clusters: bool = False,
) -> dict[str, int]:
    if do_seed_pilot_clusters:
        driver = GraphDatabase.driver(neo4j_uri, auth=neo4j_auth)
        try:
            with driver.session() as session:
                seed_pilot_clusters(session)
                print("Seeded pilot clusters.")
                return _count_layer_2(session)
        finally:
            driver.close()

    red_flag_lookup = load_red_flag_lookup(complaints_path)
    rows = build_rows(ANCHOR_MAPPINGS, red_flag_lookup)

    driver = GraphDatabase.driver(neo4j_uri, auth=neo4j_auth)
    try:
        with driver.session() as session:
            # Additive-only, idempotent (IF NOT EXISTS) -- same standard bulk-load
            # practice as load_rf2.py's SnomedConcept/Description constraints, applied
            # here to RedFlag/FollowupQuestion from the first draft rather than added
            # after the fact.
            # I-1/I-2 fix: RedFlag identity is now scoped per anchor, not
            # global by indicator text alone — a single-property uniqueness
            # constraint on rf.indicator would incorrectly forbid two
            # different anchors from each having their own RedFlag node for
            # the same indicator string. AuraDB Free is Community-edition
            # based and does not support composite/node-key uniqueness
            # constraints, so this relies on MERGE-on-the-full-pattern for
            # idempotency instead (standard Neo4j practice, same idiom
            # load_rf2.py already uses for SnomedConcept/Description).
            session.run(
                "CREATE CONSTRAINT IF NOT EXISTS FOR (q:FollowupQuestion) REQUIRE (q.anchor_id, q.text) IS UNIQUE"
            )

            total_batches = max(1, -(-len(rows) // BATCH_SIZE))  # ceil div
            for i, batch in enumerate(_batched(rows, BATCH_SIZE), start=1):
                session.run(
                    "UNWIND $rows AS row "
                    "MATCH (anchor:SnomedConcept {id: row.anchor_id}) "
                    "MERGE (anchor)-[:HAS_RED_FLAG]->(rf:RedFlag {anchor_id: row.anchor_id, indicator: row.indicator}) "
                    "SET rf.ctas_level = row.ctas_level, rf.app_severity = row.app_severity "
                    "MERGE (q:FollowupQuestion {anchor_id: row.anchor_id, text: row.followup_question}) "
                    "MERGE (rf)-[:ASKS]->(q)",
                    rows=batch,
                )
                pct = round(100 * i / total_batches)
                print(f"[{i}/{total_batches} batches] ({pct}%) wrote {len(batch)} red-flag rows")

            counts = _count_layer_2(session)
            print(
                "Done. Current graph totals -- "
                f"RedFlag: {counts['RedFlag']}, FollowupQuestion: {counts['FollowupQuestion']}, "
                f"HAS_RED_FLAG: {counts['HAS_RED_FLAG']}, ASKS: {counts['ASKS']}"
            )
            return counts
    finally:
        driver.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--neo4j-uri", required=True)
    parser.add_argument("--neo4j-user", required=True)
    parser.add_argument("--neo4j-password", required=True)
    parser.add_argument("--complaints-path", type=Path, default=DEFAULT_COMPLAINTS_PATH)
    parser.add_argument("--seed-pilot-clusters", action="store_true")
    args = parser.parse_args()
    seed(args.neo4j_uri, (args.neo4j_user, args.neo4j_password), args.complaints_path, args.seed_pilot_clusters)
