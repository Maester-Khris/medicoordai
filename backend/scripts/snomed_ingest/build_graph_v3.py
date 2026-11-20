"""SNOMED CT Neo4j v3 Graph Builder.

Purpose:
Builds a complaint-anchored SNOMED CT clinical finding subgraph in Neo4j (Layer 1
concepts, descriptions, and IS_A edges alongside reviewed patient-facing lay descriptions),
followed by Layer 2 red-flag and follow-up question overlays, graph health validation,
and optional Aura instance snapshots.

Invocation:
    cd backend && doppler run -- python -m scripts.snomed_ingest.build_graph_v3 \\
        --rf2-dir <path_to_snapshot_dir> \\
        --source-release <release_id> \\
        --lay-rule confirmed \\
        [--wipe --confirm-wipe <instance_id>] \\
        [--snapshot]

Wipe Guard:
When graph wiping is requested (--wipe), --confirm-wipe must be explicitly supplied
and match the configured AURA_INSTANCE_ID before any database connection or file reading
occurs, protecting production instances against accidental graph drops.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from dataclasses import dataclass
import json
import os
from pathlib import Path
import sys
from typing import Any

from graph.snomed_neo4j.anchor_mapping import ANCHOR_MAPPINGS, AnchorMapping
from graph.snomed_neo4j.client import Neo4jClient
from scripts.snomed_ingest.anchor_selection import (
    AnchorSpec,
    assign_concepts,
    resolve_index_depth,
)
from scripts.snomed_ingest.aura_snapshot import SnapshotResult, take_snapshot
from scripts.snomed_ingest.constants import FSN_TYPE_ID, IS_A_TYPE_ID
from scripts.snomed_ingest.graph_health import HealthReport, collect, format_report
from scripts.snomed_ingest.lay_descriptions import (
    load_lay_descriptions,
    select_for_index,
)
from scripts.snomed_ingest.layer1_writer import (
    write_concepts,
    write_constraints,
    write_descriptions,
    write_is_a,
    write_lay_descriptions,
    write_primary_anchors,
)
from scripts.snomed_ingest.rf2_reader import (
    read_concepts,
    read_descriptions,
    read_relationships,
)

DEFAULT_DATA_DIR = Path(__file__).resolve().parent / "data"
DEFAULT_OVERRIDES_PATH = DEFAULT_DATA_DIR / "index_depth_overrides.json"
DEFAULT_LAY_PATH = DEFAULT_DATA_DIR / "lay_descriptions.json"


@dataclass(frozen=True)
class BuildResult:
    report: HealthReport
    snapshot: SnapshotResult | None


def build(
    session_factory: Callable[[], Any],
    rf2_terminology_dir: Path,
    *,
    source_release: str,
    lay_rule: str = "confirmed",
    anchors_limit: int | None = None,
    wipe: bool = False,
    confirm_wipe: str | None = None,
    aura_instance_id: str | None = None,
    snapshot: bool = False,
    anchors: Sequence[AnchorMapping] | None = None,
    lay_path: Path | None = None,
    overrides_path: Path | None = None,
    seed_layer2: Callable[[], object],
    collect_health: Callable[[Sequence[str], int], HealthReport],
    snapshot_fn: Callable[[str], SnapshotResult] = take_snapshot,
) -> BuildResult:
    # 1. Guard runs BEFORE session_factory() or any file access
    if wipe:
        if not confirm_wipe or not aura_instance_id or confirm_wipe != aura_instance_id:
            raise ValueError(
                "Wipe requested but --confirm-wipe does not match configured aura_instance_id."
            )

    # 2. Overrides & Anchors
    resolved_overrides_path = (
        overrides_path if overrides_path is not None else DEFAULT_OVERRIDES_PATH
    )
    overrides: dict[str, int] = {}
    if resolved_overrides_path.is_file():
        with open(resolved_overrides_path, "r", encoding="utf-8") as f:
            overrides = json.load(f)

    input_anchors: Sequence[AnchorMapping] = (
        ANCHOR_MAPPINGS if anchors is None else anchors
    )
    deduped_anchors: list[AnchorMapping] = []
    seen_anchor_ids: set[str] = set()
    for a in input_anchors:
        if a.anchor_concept_id not in seen_anchor_ids:
            seen_anchor_ids.add(a.anchor_concept_id)
            deduped_anchors.append(a)

    if anchors_limit is not None:
        deduped_anchors = deduped_anchors[:anchors_limit]

    anchor_specs: list[AnchorSpec] = [
        AnchorSpec(
            anchor_id=a.anchor_concept_id,
            name=a.ctas_alias,
            depth=resolve_index_depth(a.ctas_alias, a.anchor_concept_id, overrides),
        )
        for a in deduped_anchors
    ]
    built_anchor_ids = [spec.anchor_id for spec in anchor_specs]
    built_anchor_ids_set = set(built_anchor_ids)

    # 3. Read RF2 files & assign concepts
    rf2_dir = Path(rf2_terminology_dir)
    concept_file = next(rf2_dir.glob("sct2_Concept_Snapshot_*.txt"))
    description_file = next(rf2_dir.glob("sct2_Description_Snapshot_*.txt"))
    relationship_file = next(rf2_dir.glob("sct2_Relationship_Snapshot_*.txt"))

    active_is_a_relationships = [
        rel
        for rel in read_relationships(relationship_file)
        if rel.active and rel.type_id == IS_A_TYPE_ID
    ]
    children: dict[str, list[str]] = {}
    for rel in active_is_a_relationships:
        children.setdefault(rel.destination_id, []).append(rel.source_id)

    assignment = assign_concepts(children, anchor_specs)
    assigned_concept_ids = set(assignment.concept_anchor.keys())

    active_concepts = [c for c in read_concepts(concept_file) if c.active]
    active_concept_map = {c.id: c for c in active_concepts}

    # Step 4 concept rows: pre-create anchors present as active in RF2
    anchor_concept_rows = [
        {
            "id": spec.anchor_id,
            "source_release": source_release,
            "effective_time": active_concept_map[spec.anchor_id].effective_time,
        }
        for spec in anchor_specs
        if spec.anchor_id in active_concept_map
    ]

    # Step 5 rows: Layer 1 assigned concepts, English descriptions, and IS_A edges
    assigned_concept_rows = [
        {
            "id": c.id,
            "source_release": source_release,
            "effective_time": c.effective_time,
        }
        for c in active_concepts
        if c.id in assigned_concept_ids
    ]

    description_rows = [
        {
            "concept_id": d.concept_id,
            "id": d.id,
            "term": d.term,
            "language_code": d.language_code,
            "is_fsn": d.type_id == FSN_TYPE_ID,
            "source_release": source_release,
            "effective_time": d.effective_time,
        }
        for d in read_descriptions(description_file)
        if d.active and d.concept_id in assigned_concept_ids and d.language_code == "en"
    ]

    is_a_rows = [
        {"source_id": rel.source_id, "destination_id": rel.destination_id}
        for rel in active_is_a_relationships
        if rel.source_id in assigned_concept_ids
        and rel.destination_id in assigned_concept_ids
    ]

    # Step 6 lay descriptions: load, filter by rule, keep built anchors only
    resolved_lay_path = lay_path if lay_path is not None else DEFAULT_LAY_PATH
    all_valid_anchor_ids = {a.anchor_concept_id for a in ANCHOR_MAPPINGS}
    if anchors is not None:
        all_valid_anchor_ids |= {a.anchor_concept_id for a in anchors}

    phrases = load_lay_descriptions(resolved_lay_path, all_valid_anchor_ids)
    selected_phrases = select_for_index(phrases, lay_rule)
    built_lay_phrases = [
        p for p in selected_phrases if p.anchor_id in built_anchor_ids_set
    ]

    # Graph writes in a single session context
    with session_factory() as session:
        if wipe:
            # (a) Delete in batches until nothing remains
            while True:
                res = session.run(
                    "MATCH (n) WITH n LIMIT 10000 DETACH DELETE n RETURN count(n) AS n"
                )
                rec = res.single()
                if rec is None or rec["n"] == 0:
                    break

            # (b) Drop ALL constraints: collect the names into a list first; old constraints
            # such as a single-property unique on FollowupQuestion.text would otherwise conflict
            # with the new composite one.
            constraints_res = session.run("SHOW CONSTRAINTS YIELD name")
            constraint_names = [row["name"] for row in constraints_res]
            for name in constraint_names:
                session.run(f"DROP CONSTRAINT `{name}` IF EXISTS")

        # Step 3: write constraints
        write_constraints(session)
        # Step 4: pre-create anchors
        write_concepts(session, anchor_concept_rows)
        # Step 5: Layer 1 writes
        write_concepts(session, assigned_concept_rows)
        write_descriptions(session, description_rows)
        write_is_a(session, is_a_rows)
        write_primary_anchors(
            session,
            [
                {"id": row["id"], "anchor_id": assignment.concept_anchor[row["id"]],
                 "depth": assignment.concept_depth[row["id"]]}
                for row in assigned_concept_rows
            ],
        )
        # Step 6: Lay descriptions
        write_lay_descriptions(session, built_lay_phrases)

    # Step 7: Layer 2 seeding (opens its own connection)
    seed_layer2()

    # Step 8: Health collection
    report = collect_health(built_anchor_ids, len(assignment.ties))

    # Step 9: Snapshot
    # A snapshot of an incomplete or over-budget graph is not a safe restore point.
    snapshot_result: SnapshotResult | None = None
    if (
        snapshot
        and aura_instance_id
        and report.anchors_loaded == report.anchors_total
        and report.nodes <= 50_000
        and report.relationships <= 75_000
    ):
        snapshot_result = snapshot_fn(aura_instance_id)

    return BuildResult(report=report, snapshot=snapshot_result)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="SNOMED CT Neo4j v3 graph builder."
    )
    parser.add_argument(
        "--rf2-dir",
        type=Path,
        required=True,
        help="Parent directory of the Terminology snapshot folder.",
    )
    parser.add_argument(
        "--source-release",
        required=True,
        help="SNOMED source release string (e.g. 20240101).",
    )
    parser.add_argument(
        "--lay-rule",
        choices=["all", "confirmed", "approved"],
        default="confirmed",
        help="Selection rule for lay descriptions (default: confirmed).",
    )
    parser.add_argument(
        "--anchors-limit",
        type=int,
        default=None,
        help="Limit number of anchors to build.",
    )
    parser.add_argument(
        "--wipe",
        action="store_true",
        help="Wipe graph and constraints before building.",
    )
    parser.add_argument(
        "--confirm-wipe",
        type=str,
        default=None,
        metavar="ID",
        help="Instance ID required to confirm graph wipe.",
    )
    parser.add_argument(
        "--snapshot",
        action="store_true",
        help="Take Aura instance snapshot after building if health checks pass.",
    )

    args = parser.parse_args()

    uri = os.environ.get("NEO4J_URI")
    username = os.environ.get("NEO4J_USERNAME")
    password = os.environ.get("NEO4J_PASSWORD")
    aura_instance_id = os.environ.get("AURA_INSTANCE_ID")

    if not uri or not username or not password:
        sys.exit(
            "Error: NEO4J_URI, NEO4J_USERNAME, and NEO4J_PASSWORD environment variables must be set."
        )

    from neo4j import GraphDatabase
    from scripts.snomed_ingest.seed_red_flags import seed

    auth = (username, password)
    driver = GraphDatabase.driver(uri, auth=auth)
    session_factory = driver.session

    def seed_layer2() -> object:
        return seed(uri, auth)

    def collect_health_fn(ids: Sequence[str], collisions: int) -> HealthReport:
        client = Neo4jClient(uri, auth)
        try:
            return collect(client, ids, collisions=collisions)
        finally:
            client.close()

    rf2_terminology_dir = (
        args.rf2_dir / "Terminology"
        if (args.rf2_dir / "Terminology").is_dir()
        else args.rf2_dir
    )

    try:
        res = build(
            session_factory,
            rf2_terminology_dir,
            source_release=args.source_release,
            lay_rule=args.lay_rule,
            anchors_limit=args.anchors_limit,
            wipe=args.wipe,
            confirm_wipe=args.confirm_wipe,
            aura_instance_id=aura_instance_id,
            snapshot=args.snapshot,
            seed_layer2=seed_layer2,
            collect_health=collect_health_fn,
        )
    finally:
        driver.close()

    print(format_report(res.report))
    if res.snapshot is not None:
        print(f"Snapshot: ok={res.snapshot.ok} detail={res.snapshot.detail}")
    else:
        print("Snapshot: skipped")


if __name__ == "__main__":
    main()
