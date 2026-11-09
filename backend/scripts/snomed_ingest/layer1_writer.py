"""Layer 1 Neo4j graph writers for SNOMED CT ingestion and lay descriptions.

Lay descriptions are stored as separate Description nodes with kind "lay"
(linked to SnomedConcept nodes via HAS_DESCRIPTION). They represent reviewed
patient wordings rather than official SNOMED CT content, and must remain
distinguishable from official descriptions to preserve terminology
provenance while enabling patient-friendly semantic search and matching.
"""

from itertools import islice
from typing import Any, Iterable, Iterator, Protocol, Sequence, TypeVar

from scripts.snomed_ingest.lay_descriptions import LayPhrase, lay_description_id

# Batch size for UNWIND-based writes. Approved deviation from the plan's literal
# one-row-per-session.run() code: the Clinical Finding subset is ~129k concepts /
# ~490k descriptions / ~264k IS_A relationships, so unbatched writes are ~1.37M
# individual network round-trips to Neo4j Aura — a multi-hour, fragile operation.
# Batching with UNWIND preserves identical MERGE semantics (including the
# order-dependent last-FSN-wins behavior on c.fsn) while cutting round-trips by
# ~3 orders of magnitude.
BATCH_SIZE = 1000

T = TypeVar("T")


class Session(Protocol):
    def run(self, cypher: str, **params: Any) -> Any: ...


def _batched(iterable: Iterable[T], size: int) -> Iterator[list[T]]:
    it = iter(iterable)
    while batch := list(islice(it, size)):
        yield batch


def write_constraints(session: Session) -> None:
    # Approved deviation from the plan's literal code (same category as UNWIND
    # batching above): without a uniqueness constraint, every MERGE on {id: ...}
    # does a full label scan, which degrades toward O(n) per row as the graph
    # grows — observed directly (68,121/129,425 concepts in ~22 min before this
    # was added). Standard Neo4j bulk-load practice; additive only, no semantic
    # change; safe to run every invocation via IF NOT EXISTS.
    session.run(
        "CREATE CONSTRAINT IF NOT EXISTS FOR (c:SnomedConcept) REQUIRE c.id IS UNIQUE"
    )
    session.run(
        "CREATE CONSTRAINT IF NOT EXISTS FOR (d:Description) REQUIRE d.id IS UNIQUE"
    )


def write_concepts(session: Session, rows: Iterable[dict]) -> None:
    for batch in _batched(rows, BATCH_SIZE):
        session.run(
            "UNWIND $rows AS row "
            "MERGE (c:SnomedConcept {id: row.id}) "
            "SET c.source_release = row.source_release, c.effective_time = row.effective_time",
            rows=batch,
        )


def write_descriptions(session: Session, rows: Iterable[dict]) -> None:
    for batch in _batched(rows, BATCH_SIZE):
        session.run(
            "UNWIND $rows AS row "
            "MATCH (c:SnomedConcept {id: row.concept_id}) "
            "MERGE (d:Description {id: row.id}) "
            "SET d.term = row.term, d.language_code = row.language_code, "
            "    d.is_fsn = row.is_fsn, d.source_release = row.source_release, "
            "    d.effective_time = row.effective_time "
            "MERGE (c)-[:HAS_DESCRIPTION]->(d) "
            "WITH c, row "
            "FOREACH (_ IN CASE WHEN row.is_fsn THEN [1] ELSE [] END | SET c.fsn = row.term)",
            rows=batch,
        )


def write_is_a(session: Session, rows: Iterable[dict]) -> None:
    for batch in _batched(rows, BATCH_SIZE):
        session.run(
            "UNWIND $rows AS row "
            "MATCH (child:SnomedConcept {id: row.source_id}) "
            "MATCH (parent:SnomedConcept {id: row.destination_id}) "
            "MERGE (child)-[:IS_A]->(parent)",
            rows=batch,
        )


def write_lay_descriptions(session: Session, phrases: Sequence[LayPhrase]) -> None:
    rows = [
        {
            "lay_id": lay_description_id(phrase.anchor_id, phrase.text),
            "anchor_id": phrase.anchor_id,
            "term": phrase.text,
            "source": phrase.source,
            "status": phrase.status,
        }
        for phrase in phrases
    ]
    for batch in _batched(rows, BATCH_SIZE):
        session.run(
            "UNWIND $rows AS row "
            "MATCH (c:SnomedConcept {id: row.anchor_id}) "
            "MERGE (d:Description {id: row.lay_id}) "
            'SET d.term = row.term, d.language_code = "en", d.kind = "lay", '
            "d.source = row.source, d.status = row.status, d.is_fsn = false "
            "MERGE (c)-[:HAS_DESCRIPTION]->(d)",
            rows=batch,
        )
