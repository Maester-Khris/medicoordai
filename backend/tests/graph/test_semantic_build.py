import json
import sys
from pathlib import Path

import numpy as np
import pytest

from graph.semantic import build as b
from graph.semantic.index import IndexRow, SemanticIndex
from graph.semantic.settings import SemanticSettings


def _settings(tmp_path, **kw):
    base = dict(model_dir=tmp_path / "model", index_dir=tmp_path / "idx", score_threshold=0.5, gap_margin=0.02, lay_rule="confirmed")
    base.update(kw)
    return SemanticSettings(**base)


CARD = b.ModelCard(model_id="fake", pooling="mean", prefix="", max_len=64, model_sha256="sha1")


class FakeClient:
    def __init__(self, english=None, lay=None, build=None):
        self.english = english if english is not None else [
            {"concept_id": "c1", "anchor_id": "a1", "text": "Headache (finding)", "is_fsn": True},
            {"concept_id": "c1", "anchor_id": "a1", "text": "Headache", "is_fsn": False},
            {"concept_id": "c2", "anchor_id": "a2", "text": "Cough", "is_fsn": False},
        ]
        self.lay = lay if lay is not None else [{"concept_id": "a1", "anchor_id": "a1", "text": "my head is pounding"}]
        self.build = build or [{"release": "20240101", "concepts": 3}]
        self.lay_params = []

    def run_query(self, query, params):
        if query == b.Q_ENGLISH_ROWS:
            return self.english
        if query == b.Q_LAY_ROWS:
            self.lay_params.append(params)
            return self.lay
        if query == b.Q_GRAPH_BUILD:
            return self.build
        raise AssertionError(f"unexpected query {query}")


class FakeEmbedder:
    name, dim, ready = "fake", 2, True

    def __init__(self, fail_on=None):
        self.calls, self.fail_on = [], fail_on

    def embed(self, text):
        self.calls.append(text)
        if self.fail_on is not None and len(self.calls) == self.fail_on:
            raise RuntimeError("boom")
        v = np.array([len(text), 1.0], dtype=np.float32)
        return v / np.linalg.norm(v)


def test_fetch_rows_only_includes_lay_phrases_allowed_by_the_rule():
    client = FakeClient()
    rows = b.fetch_index_rows(client, "confirmed")
    assert client.lay_params[-1] == {"statuses": ["confirmed", "approved"]}
    b.fetch_index_rows(client, "all")
    assert client.lay_params[-1] == {"statuses": ["generated", "confirmed", "approved"]}
    b.fetch_index_rows(client, "approved")
    assert client.lay_params[-1] == {"statuses": ["approved"]}
    with pytest.raises(ValueError):
        b.fetch_index_rows(client, "bogus")
    # the FSN tag is stripped, the duplicate of the synonym collapses, and the order is deterministic
    assert rows == [IndexRow("a1", "a1", "my head is pounding", "lay"), IndexRow("c1", "a1", "Headache", "english"),
                    IndexRow("c2", "a2", "Cough", "english")]


def test_build_embeds_each_row_once_and_writes_atomically(tmp_path):
    client, embedder, s = FakeClient(), FakeEmbedder(), _settings(tmp_path)
    manifest = b.build_index(client, embedder, s, s.index_dir, card=CARD)
    assert sorted(embedder.calls) == sorted(["my head is pounding", "Headache", "Cough"])  # once per row
    assert manifest.rows == 3 and manifest.dim == 2 and manifest.model_id == "fake" and manifest.lay_rule == "confirmed"
    assert SemanticIndex.load(s.index_dir, b.expected_manifest(b.fetch_index_rows(client, "confirmed"), CARD, 2, s, "20240101:3")).rows
    # a failure part-way leaves nothing behind
    s2 = _settings(tmp_path, index_dir=tmp_path / "idx2")
    with pytest.raises(RuntimeError):
        b.build_index(client, FakeEmbedder(fail_on=2), s2, s2.index_dir, card=CARD)
    assert not s2.index_dir.exists()


def test_index_state_is_stale_when_graph_hash_changed(tmp_path):
    client, s = FakeClient(), _settings(tmp_path)
    assert b.index_state(s, client, CARD, dim=2) == "missing"
    b.build_index(client, FakeEmbedder(), s, s.index_dir, card=CARD)
    assert b.index_state(s, client, CARD, dim=2) == "ready"
    client.english.append({"concept_id": "c3", "anchor_id": "a2", "text": "Wheeze", "is_fsn": False})
    assert b.index_state(s, client, CARD, dim=2) == "stale"


def test_ensure_exits_zero_when_neo4j_is_unreachable(tmp_path):
    def unreachable():
        raise ConnectionError("neo4j down")

    spawned = []
    assert b.ensure(_settings(tmp_path), unreachable, lambda: (CARD, 2), spawn=spawned.append) == 0
    assert spawned == []


def test_ensure_spawns_background_build_when_missing(tmp_path):
    spawned = []
    assert b.ensure(_settings(tmp_path), FakeClient, lambda: (CARD, 2), spawn=spawned.append) == 0
    (cmd,) = spawned
    assert cmd[:3] == ["nice", "-n", "19"]
    assert "graph.semantic.build" in cmd and cmd[-1] == "run"


def test_ensure_does_nothing_when_the_index_is_ready(tmp_path):
    client, s, spawned = FakeClient(), _settings(tmp_path), []
    b.build_index(client, FakeEmbedder(), s, s.index_dir, card=CARD)
    assert b.ensure(s, lambda: client, lambda: (CARD, 2), spawn=spawned.append) == 0
    assert spawned == []


def test_a_model_problem_in_ensure_is_logged_not_raised(tmp_path):
    def no_model():
        raise FileNotFoundError("export.json")

    spawned = []
    assert b.ensure(_settings(tmp_path), FakeClient, no_model, spawn=spawned.append) == 0 and spawned == []


def test_run_skips_when_another_build_holds_the_lock(tmp_path):
    s = _settings(tmp_path)
    s.index_dir.parent.mkdir(parents=True, exist_ok=True)
    with b.build_lock(s.index_dir) as first:
        assert first is True
        with b.build_lock(s.index_dir) as second:
            assert second is False
    with b.build_lock(s.index_dir) as again:
        assert again is True


def test_load_model_card_reads_export_json(tmp_path):
    (tmp_path / "export.json").write_text(json.dumps({"model_key": "biolord", "pooling": "mean", "prefix": "", "max_len": 64,
                                                      "model_sha256": "abc"}))
    assert b.load_model_card(tmp_path) == b.ModelCard("biolord", "mean", "", 64, "abc")
    with pytest.raises(FileNotFoundError):
        b.load_model_card(tmp_path / "missing")
