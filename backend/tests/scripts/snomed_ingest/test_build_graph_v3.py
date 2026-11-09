import json
from pathlib import Path

import pytest

from graph.snomed_neo4j.anchor_mapping import AnchorMapping
from scripts.snomed_ingest.aura_snapshot import SnapshotResult
from scripts.snomed_ingest.build_graph_v3 import BuildResult, build
from scripts.snomed_ingest.constants import FSN_TYPE_ID, IS_A_TYPE_ID
from scripts.snomed_ingest.graph_health import HealthReport

SYNONYM = "900000000000013009"
A1, A2, CHILD, GRANDCHILD, OTHER = "111", "222", "333", "444", "999"


def _write(path: Path, header: list[str], rows: list[list[str]]) -> None:
    path.write_text("\n".join("\t".join(r) for r in [header, *rows]) + "\n", encoding="utf-8")


@pytest.fixture
def rf2(tmp_path):
    t = tmp_path / "Terminology"
    t.mkdir()
    _write(t / "sct2_Concept_Snapshot_X.txt", ["id", "effectiveTime", "active", "moduleId", "definitionStatusId"],
           [[c, "20240101", "1", "m", "d"] for c in (A1, A2, CHILD, GRANDCHILD, OTHER)])
    desc = ["id", "effectiveTime", "active", "moduleId", "conceptId", "languageCode", "typeId", "term", "caseSignificanceId"]
    _write(t / "sct2_Description_Snapshot_X.txt", desc, [
        ["d1", "20240101", "1", "m", A1, "en", FSN_TYPE_ID, "Headache (finding)", "c"],
        ["d2", "20240101", "1", "m", CHILD, "en", SYNONYM, "Tension headache", "c"],
        ["d3", "20240101", "1", "m", CHILD, "fr", SYNONYM, "Céphalée de tension", "c"],
        ["d4", "20240101", "1", "m", GRANDCHILD, "en", SYNONYM, "Too deep", "c"],
        ["d5", "20240101", "1", "m", A2, "en", SYNONYM, "Cough", "c"],
    ])
    rel = ["id", "effectiveTime", "active", "moduleId", "sourceId", "destinationId", "relationshipGroup", "typeId",
           "characteristicTypeId", "modifierId"]
    _write(t / "sct2_Relationship_Snapshot_X.txt", rel, [
        ["r1", "20240101", "1", "m", CHILD, A1, "0", IS_A_TYPE_ID, "c", "m"],
        ["r2", "20240101", "1", "m", GRANDCHILD, CHILD, "0", IS_A_TYPE_ID, "c", "m"],
        ["r3", "20240101", "1", "m", OTHER, A2, "0", IS_A_TYPE_ID, "c", "m"],
    ])
    return t


@pytest.fixture
def lay_file(tmp_path):
    p = tmp_path / "lay.json"
    p.write_text(json.dumps({"version": 1, "phrases": [
        {"anchor_id": A1, "text": "my head is pounding", "source": "m", "status": "confirmed"},
        {"anchor_id": A1, "text": "head feels tight", "source": "m", "status": "generated"},
    ]}))
    return p


ANCHORS = [AnchorMapping("Headache", A1, "Headache (finding)", "r"), AnchorMapping("Cough", A2, "Cough", "r")]


class FakeResult:
    def __iter__(self):
        return iter([])

    def single(self):
        return {"n": 0}


class FakeSession:
    def __init__(self, log):
        self.log = log

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def run(self, cypher, **params):
        self.log.append(("cypher", cypher, params))
        return FakeResult()


def _kind(cypher: str) -> str:
    for needle, kind in (("DETACH DELETE", "wipe"), ("DROP CONSTRAINT", "wipe"), ("SHOW CONSTRAINTS", "wipe"),
                         ("CREATE CONSTRAINT", "constraint"), ('d.kind = "lay"', "lay"),
                         ("HAS_DESCRIPTION", "descriptions"), ("MERGE (child)-[:IS_A]", "is_a"),
                         ("MERGE (c:SnomedConcept {id: row.id})", "concepts")):
        if needle in cypher:
            return kind
    return "other:" + cypher[:40]


def _report(loaded=2, total=2):
    return HealthReport(nodes=10, relationships=10, max_over_median_degree=1.0, max_is_a_in_degree=1, max_asks_in_degree=1,
                        max_red_flag_out_degree=1, component_count=1, largest_component_share=1.0,
                        anchors_loaded=loaded, anchors_total=total, collisions=0)


def _run(rf2, lay_file, tmp_path, log=None, **overrides):
    log = [] if log is None else log
    factory_calls = []

    def factory():
        factory_calls.append(1)
        return FakeSession(log)

    seen_anchor_ids = []
    report = overrides.pop("report", None)

    def collect_health(anchor_ids, collisions):
        log.append(("health",))
        seen_anchor_ids.append(list(anchor_ids))
        return report or _report(len(anchor_ids), len(anchor_ids))

    def snapshot_fn(instance_id):
        log.append(("snapshot", instance_id))
        return SnapshotResult(True, "ok")

    kwargs = dict(source_release="test", lay_rule="confirmed", anchors_limit=None, wipe=False, confirm_wipe=None,
                  aura_instance_id="inst1", snapshot=True, anchors=ANCHORS, lay_path=lay_file,
                  overrides_path=tmp_path / "none.json", seed_layer2=lambda: log.append(("layer2",)),
                  collect_health=collect_health, snapshot_fn=snapshot_fn)
    kwargs.update(overrides)
    result = build(factory, rf2, **kwargs)
    return result, log, factory_calls, seen_anchor_ids


def _written_ids(log, kind):
    return [r["id"] for e in log if e[0] == "cypher" and _kind(e[1]) == kind for r in e[2]["rows"]]


def test_wipe_without_confirm_flag_raises_and_runs_nothing(rf2, lay_file, tmp_path):
    log = []
    with pytest.raises(ValueError):
        _run(rf2, lay_file, tmp_path, log, wipe=True, confirm_wipe=None)
    assert log == []


def test_wipe_with_mismatched_confirm_raises(rf2, lay_file, tmp_path):
    log = []
    with pytest.raises(ValueError):
        _run(rf2, lay_file, tmp_path, log, wipe=True, confirm_wipe="other-instance")
    assert log == []
    with pytest.raises(ValueError):  # no instance id configured at all
        _run(rf2, lay_file, tmp_path, log, wipe=True, confirm_wipe="inst1", aura_instance_id=None)
    assert log == []


def test_steps_run_in_the_documented_order(rf2, lay_file, tmp_path):
    result, log, _, _ = _run(rf2, lay_file, tmp_path, wipe=True, confirm_wipe="inst1")
    steps = []
    for entry in log:
        step = _kind(entry[1]) if entry[0] == "cypher" else entry[0]
        if not steps or steps[-1] != step:
            steps.append(step)
    first = {s: steps.index(s) for s in steps}
    assert first["wipe"] < first["constraint"] < first["concepts"] < first["descriptions"] < first["is_a"] < first["lay"] \
        < first["layer2"] < first["health"] < first["snapshot"]
    # anchors are written before any description, so depth-0 anchors always exist
    concept_calls = [e for e in log if e[0] == "cypher" and _kind(e[1]) == "concepts"]
    assert {r["id"] for r in concept_calls[0][2]["rows"]} == {A1, A2}
    assert isinstance(result, BuildResult) and result.snapshot.ok


def test_english_only_descriptions_are_written(rf2, lay_file, tmp_path):
    _, log, _, _ = _run(rf2, lay_file, tmp_path)
    rows = [r for e in log if e[0] == "cypher" and _kind(e[1]) == "descriptions" for r in e[2]["rows"]]
    assert rows and {r["language_code"] for r in rows} == {"en"}
    # depth 1 default: the grandchild and the unrelated concept are not loaded
    assert GRANDCHILD not in {r["concept_id"] for r in rows} and OTHER not in {r["concept_id"] for r in rows}
    assert {r["concept_id"] for r in rows} == {A1, A2, CHILD}
    lay_rows = [r for e in log if e[0] == "cypher" and _kind(e[1]) == "lay" for r in e[2]["rows"]]
    assert [r["term"] for r in lay_rows] == ["my head is pounding"]  # rule "confirmed" drops the generated one


def test_snapshot_is_skipped_when_anchor_coverage_incomplete(rf2, lay_file, tmp_path):
    result, log, _, _ = _run(rf2, lay_file, tmp_path, report=_report(loaded=1, total=2))
    assert ("snapshot", "inst1") not in log and result.snapshot is None


def test_snapshot_flag_off_skips_the_snapshot(rf2, lay_file, tmp_path):
    result, log, _, _ = _run(rf2, lay_file, tmp_path, snapshot=False)
    assert not any(e[0] == "snapshot" for e in log) and result.snapshot is None


def test_anchors_limit_builds_only_that_many_anchors(rf2, lay_file, tmp_path):
    _, log, _, seen = _run(rf2, lay_file, tmp_path, anchors_limit=1)
    assert seen == [[A1]]
    ids = set(_written_ids(log, "concepts"))
    assert ids == {A1, CHILD}
