import inspect

from scripts.snomed_ingest import load_rf2
from scripts.snomed_ingest.lay_descriptions import LayPhrase, lay_description_id
from scripts.snomed_ingest.layer1_writer import (
    BATCH_SIZE,
    write_concepts,
    write_constraints,
    write_descriptions,
    write_is_a,
    write_lay_descriptions,
)


class FakeSession:
    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    def run(self, cypher, **params):
        self.calls.append((cypher, params))


def test_load_rf2_still_issues_the_same_cypher_in_the_same_order():
    s = FakeSession()
    write_constraints(s)
    write_concepts(s, [{"id": "1"}])
    write_descriptions(s, [{"id": "d"}])
    write_is_a(s, [{"source_id": "1", "destination_id": "2"}])
    assert [c for c, _ in s.calls] == [
        "CREATE CONSTRAINT IF NOT EXISTS FOR (c:SnomedConcept) REQUIRE c.id IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (d:Description) REQUIRE d.id IS UNIQUE",
        "UNWIND $rows AS row "
        "MERGE (c:SnomedConcept {id: row.id}) "
        "SET c.source_release = row.source_release, c.effective_time = row.effective_time",
        "UNWIND $rows AS row "
        "MATCH (c:SnomedConcept {id: row.concept_id}) "
        "MERGE (d:Description {id: row.id}) "
        "SET d.term = row.term, d.language_code = row.language_code, "
        "    d.is_fsn = row.is_fsn, d.source_release = row.source_release, "
        "    d.effective_time = row.effective_time "
        "MERGE (c)-[:HAS_DESCRIPTION]->(d) "
        "WITH c, row "
        "FOREACH (_ IN CASE WHEN row.is_fsn THEN [1] ELSE [] END | SET c.fsn = row.term)",
        "UNWIND $rows AS row "
        "MATCH (child:SnomedConcept {id: row.source_id}) "
        "MATCH (parent:SnomedConcept {id: row.destination_id}) "
        "MERGE (child)-[:IS_A]->(parent)",
    ]
    assert s.calls[2][1] == {"rows": [{"id": "1"}]}


def test_load_rf2_delegates_to_the_writers_in_order():
    source = inspect.getsource(load_rf2.load)
    positions = [source.index(f"{name}(") for name in ("write_constraints", "write_concepts", "write_descriptions", "write_is_a")]
    assert positions == sorted(positions)
    assert "session.run(" not in source


def test_lay_writer_sets_kind_language_and_links_to_the_anchor():
    s = FakeSession()
    write_lay_descriptions(s, [LayPhrase("68235000", "my nose is blocked", "gpt-4o-mini", "confirmed")])
    (cypher, params), = s.calls
    for fragment in ("d.kind = \"lay\"", "d.language_code = \"en\"", "d.is_fsn = false", "MATCH (c:SnomedConcept {id: row.anchor_id})",
                     "MERGE (c)-[:HAS_DESCRIPTION]->(d)"):
        assert fragment in cypher.replace("'", '"')
    assert params["rows"] == [{
        "lay_id": lay_description_id("68235000", "my nose is blocked"), "anchor_id": "68235000",
        "term": "my nose is blocked", "source": "gpt-4o-mini", "status": "confirmed",
    }]


def test_lay_writer_batches_at_1000():
    assert BATCH_SIZE == 1000
    s = FakeSession()
    write_lay_descriptions(s, [LayPhrase("1", f"phrase number {i}", "m", "confirmed") for i in range(2500)])
    assert [len(p["rows"]) for _, p in s.calls] == [1000, 1000, 500]
