import json
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from graph.semantic.index import IndexManifest, IndexRow, SemanticIndex, rows_digest, write_index  # noqa: E402
from scripts.embedding_eval.calibrate import Thresholds  # noqa: E402
from scripts.embedding_eval.eval_index import ScreenReport, evaluate, load_queries, passes_screen, wilson_ci  # noqa: E402


def _unit(*weights: float) -> np.ndarray:
    v = np.array(weights, dtype=np.float32)
    return v / np.linalg.norm(v)


@pytest.fixture
def toy_index(tmp_path):
    rows = [IndexRow(f"c{i}", f"a{i}", f"phrase {i}", "english") for i in range(1, 7)]
    manifest = IndexManifest(model_id="toy", dim=6, pooling="mean", prefix="", lay_rule="confirmed", rows=6,
                             rows_sha256=rows_digest(rows), graph_build_id="g", model_sha256="s")
    write_index(tmp_path / "idx", rows, np.eye(6, dtype=np.float32), manifest)
    return SemanticIndex.load(tmp_path / "idx", manifest)


class MapEmbedder:
    name, dim, ready = "toy", 6, True

    def __init__(self, vectors):
        self.vectors, self.calls = vectors, []

    def embed(self, text):
        self.calls.append(text)
        return self.vectors[text]


VECTORS = {
    "q1": _unit(1, 0, 0, 0, 0, 0),                       # gold a1: rank 1
    "q2": _unit(0.9, 0.5, 0, 0, 0, 0),                   # gold a2: rank 2
    "q3": _unit(0.9, 0.8, 0.7, 0.6, 0.5, 0.4),           # gold a6: rank 6 (outside the top 5)
    "n_far": _unit(1, 1, 1, 1, 1, 1),                    # equally close to everything (top 0.41): abstains
    "n_close": _unit(0, 0, 0, 0, 1, 0),                  # looks exactly like a5: a false match
}


def test_hit_rates_on_a_toy_index(toy_index):
    queries = [{"message": "q1", "anchor_id": "a1"}, {"message": "q2", "anchor_id": "a2"}, {"message": "q3", "anchor_id": "a6"}]
    negatives = [{"text": "n_far"}, {"text": "n_close"}, {"text": "😀"}]
    embedder = MapEmbedder(VECTORS)
    report = evaluate(toy_index, embedder, queries, negatives, Thresholds(threshold=0.5, margin=0.1, in_scope_retained=0, false_match=0))
    assert report.hit1 == pytest.approx(1 / 3) and report.hit5 == pytest.approx(2 / 3)
    assert report.in_scope_retained == pytest.approx(2 / 3)  # q3 has a top score of 0.55 but only a 0.06 gap to the second anchor
    assert report.false_match == pytest.approx(1 / 3)       # n_close accepted; n_far abstains; the emoji is never embedded
    assert "😀" not in embedder.calls
    lo, hi = report.hit5_ci95
    assert 0 <= lo < report.hit5 < hi <= 1
    assert 0 <= report.p50_ms <= report.p95_ms


def test_wilson_interval():
    lo, hi = wilson_ci(40, 50)
    assert lo == pytest.approx(0.670, abs=0.01) and hi == pytest.approx(0.892, abs=0.01)
    assert wilson_ci(0, 0) == (0.0, 1.0)


def _report(**kw):
    base = dict(hit1=0.6, hit5=0.85, hit5_ci95=(0.78, 0.9), false_match=0.04, in_scope_retained=0.8, p50_ms=3.0, p95_ms=5.0)
    base.update(kw)
    return ScreenReport(**base)


def test_passes_screen_requires_both_conditions():
    assert passes_screen(_report())
    assert not passes_screen(_report(hit5_ci95=(0.74, 0.9)))   # lower bound below 75%
    assert not passes_screen(_report(false_match=0.06))        # too many out-of-scope messages accepted
    assert passes_screen(_report(hit5_ci95=(0.75, 0.9), false_match=0.05))


def test_load_queries_maps_idx_to_anchor_id_and_filters_unconfirmed(tmp_path):
    from graph.snomed_neo4j.anchor_mapping import ANCHOR_MAPPINGS
    path = tmp_path / "q.json"
    path.write_text(json.dumps([{"idx": 0, "message": "a", "agree_top3": True}, {"idx": 3, "message": "b", "agree_top3": False},
                                {"idx": 3, "message": "c"}]))
    assert [q["anchor_id"] for q in load_queries([path], valid_only=False)] == [ANCHOR_MAPPINGS[0].anchor_concept_id,
                                                                               ANCHOR_MAPPINGS[3].anchor_concept_id,
                                                                               ANCHOR_MAPPINGS[3].anchor_concept_id]
    assert [q["message"] for q in load_queries([path], valid_only=True)] == ["a", "c"]  # a missing label counts as unflagged
