import dataclasses
import os

import numpy as np
import pytest

import graph.semantic.index as index_module
from graph.semantic.index import (
    Hit,
    IndexManifest,
    IndexRow,
    SemanticIndex,
    StaleIndexError,
    rows_digest,
    write_index,
)

ROWS = [
    IndexRow("c1", "a1", "headache", "english"),
    IndexRow("c2", "a2", "dry cough", "english"),
    IndexRow("lay:a1:x", "a1", "my head is pounding", "lay"),
]
MATRIX = np.array([[1.0, 0.0], [0.0, 1.0], [0.6, 0.8]], dtype=np.float32)


def _manifest(**kw):
    base = dict(model_id="biolord", dim=2, pooling="mean", prefix="", lay_rule="confirmed", rows=3,
                rows_sha256=rows_digest(ROWS), graph_build_id="g1", model_sha256="m1")
    base.update(kw)
    return IndexManifest(**base)


def test_search_returns_rows_in_descending_score_order(tmp_path):
    write_index(tmp_path / "idx", ROWS, MATRIX, _manifest())
    idx = SemanticIndex.load(tmp_path / "idx", _manifest())
    hits = idx.search(np.array([0.0, 1.0], dtype=np.float32), top_n=2)
    assert [h.row.concept_id for h in hits] == ["c2", "lay:a1:x"]
    assert hits[0].score == pytest.approx(1.0) and hits[1].score == pytest.approx(0.8)
    assert isinstance(hits[0], Hit)
    assert len(idx.search(np.array([1.0, 0.0], dtype=np.float32), top_n=10)) == 3  # top_n larger than the index is fine


@pytest.mark.parametrize("field,value", [("model_id", "bge"), ("lay_rule", "all"), ("rows_sha256", "deadbeef"),
                                         ("graph_build_id", "g2"), ("model_sha256", "m2"), ("prefix", "query: "),
                                         ("pooling", "cls"), ("dim", 3), ("rows", 4)])
def test_load_rejects_manifest_with_different_model_or_lay_rule_or_hash(tmp_path, field, value):
    write_index(tmp_path / "idx", ROWS, MATRIX, _manifest())
    with pytest.raises(StaleIndexError):
        SemanticIndex.load(tmp_path / "idx", dataclasses.replace(_manifest(), **{field: value}))


def test_load_rejects_a_matrix_whose_row_count_differs_from_the_manifest(tmp_path):
    write_index(tmp_path / "idx", ROWS, MATRIX, _manifest())
    np.save(tmp_path / "idx" / "matrix.npy", MATRIX[:2])  # corrupt: manifest still says 3 rows
    with pytest.raises(StaleIndexError):
        SemanticIndex.load(tmp_path / "idx", _manifest())


def test_write_is_atomic_a_crash_before_rename_leaves_the_old_index(tmp_path, monkeypatch):
    write_index(tmp_path / "idx", ROWS, MATRIX, _manifest())

    def boom(*a, **k):
        raise OSError("crash")

    monkeypatch.setattr(index_module.os, "rename", boom)
    monkeypatch.setattr(index_module.os, "replace", boom)
    new_rows = ROWS[:2]
    with pytest.raises(OSError):
        write_index(tmp_path / "idx", new_rows, MATRIX[:2], _manifest(rows=2, rows_sha256=rows_digest(new_rows), graph_build_id="g2"))
    monkeypatch.undo()
    assert SemanticIndex.load(tmp_path / "idx", _manifest()).search(np.array([1.0, 0.0], dtype=np.float32), 1)[0].row.concept_id == "c1"


def test_failed_first_write_leaves_no_index_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(index_module.os, "rename", lambda *a, **k: (_ for _ in ()).throw(OSError("crash")))
    monkeypatch.setattr(index_module.os, "replace", lambda *a, **k: (_ for _ in ()).throw(OSError("crash")))
    with pytest.raises(OSError):
        write_index(tmp_path / "idx", ROWS, MATRIX, _manifest())
    monkeypatch.undo()
    assert not (tmp_path / "idx").exists()
    with pytest.raises(StaleIndexError):
        SemanticIndex.load(tmp_path / "idx", _manifest())


def test_a_leftover_tmp_directory_does_not_block_the_next_write(tmp_path):
    (tmp_path / "idx.tmp").mkdir()
    (tmp_path / "idx.tmp" / "junk").write_text("x")
    write_index(tmp_path / "idx", ROWS, MATRIX, _manifest())
    assert not (tmp_path / "idx.tmp").exists()
    assert SemanticIndex.load(tmp_path / "idx", _manifest()).rows == ROWS


def test_missing_directory_raises_StaleIndexError(tmp_path):
    with pytest.raises(StaleIndexError):
        SemanticIndex.load(tmp_path / "nope", _manifest())


def test_rows_digest_changes_with_any_row_field():
    assert rows_digest(ROWS) == rows_digest(list(ROWS))
    assert rows_digest(ROWS) != rows_digest(ROWS[:2])
    assert rows_digest(ROWS) != rows_digest([dataclasses.replace(ROWS[0], text="head ache"), *ROWS[1:]])
