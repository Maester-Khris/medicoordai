import json
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

from graph.semantic.build import ModelCard
from graph.semantic.index import IndexManifest, IndexRow, rows_digest, write_index
from graph.semantic.settings import SemanticSettings
from graph.snomed_neo4j.semantic_provider import Neo4jSemanticProvider

CARD = ModelCard(model_id="fake", pooling="mean", prefix="", max_len=64, model_sha256="sha1")


class FakeEmbedder:
    name, dim = "fake", 2

    def __init__(self):
        self.ready, self.warmed = False, False

    def warm_up(self):
        self.warmed, self.ready = True, True

    def embed(self, text):
        return np.array([1.0, 0.0], dtype=np.float32)


def _write(index_dir, n_rows, **manifest_kw):
    rows = [IndexRow(f"c{i}", "a1", f"phrase {i}", "english") for i in range(n_rows)]
    fields = dict(model_id="fake", dim=2, pooling="mean", prefix="", lay_rule="confirmed", rows=n_rows,
                  rows_sha256=rows_digest(rows), graph_build_id=f"g{n_rows}", model_sha256="sha1")
    fields.update(manifest_kw)
    write_index(index_dir, rows, np.ones((n_rows, 2), dtype=np.float32), IndexManifest(**fields))


@pytest.fixture
def env(tmp_path, monkeypatch):
    for k, v in (("NEO4J_URI", "bolt://x"), ("NEO4J_USERNAME", "u"), ("NEO4J_PASSWORD", "p")):
        monkeypatch.setenv(k, v)
    model_dir, index_dir = tmp_path / "model", tmp_path / "idx"
    model_dir.mkdir()
    (model_dir / "export.json").write_text(json.dumps({"model_key": "fake", "pooling": "mean", "prefix": "", "max_len": 64,
                                                       "model_sha256": "sha1", "dim": 2}))
    settings = SemanticSettings(model_dir=model_dir, index_dir=index_dir, score_threshold=0.5, gap_margin=0.1, lay_rule="confirmed")
    clock = [1000.0]
    with patch("graph.snomed_neo4j.provider.Neo4jClient"):
        provider = Neo4jSemanticProvider(settings=settings, embedder_factory=lambda s, card: FakeEmbedder(), clock=lambda: clock[0])
    return provider, index_dir, clock


def test_nothing_loads_without_autoload_and_initialise_reports_building_without_an_index(env):
    provider, index_dir, _ = env
    assert provider.semantic_status()["state"] == "disabled"  # the constructor started no thread and loaded nothing
    provider.initialise()
    assert provider.semantic_status() == {"state": "building", "model": "fake", "rows": 0}


def test_provider_loads_a_newer_valid_index_and_ignores_a_stale_one(env):
    provider, index_dir, clock = env
    provider.initialise()
    _write(index_dir, 3)
    assert provider.maybe_reload(force=True) is True
    assert provider.semantic_status() == {"state": "ready", "model": "fake", "rows": 3}

    _write(index_dir, 2)  # a newer valid build appears
    clock[0] += 10
    assert provider.maybe_reload() is False  # rate limited: checked less than SEMANTIC_RELOAD_S ago
    assert provider.semantic_status()["rows"] == 3
    clock[0] += 61
    assert provider.maybe_reload() is True and provider.semantic_status()["rows"] == 2

    _write(index_dir, 5, model_id="other-model")  # built for a different model: must be ignored, old index keeps serving
    clock[0] += 61
    assert provider.maybe_reload() is False
    assert provider.semantic_status() == {"state": "ready", "model": "fake", "rows": 2}

    clock[0] += 61
    assert provider.maybe_reload() is False  # nothing changed


def test_a_corrupt_index_never_replaces_a_working_one(env):
    provider, index_dir, clock = env
    provider.initialise()
    _write(index_dir, 3)
    assert provider.maybe_reload(force=True) is True
    np.save(index_dir / "matrix.npy", np.ones((1, 2), dtype=np.float32))  # row count no longer matches the manifest
    clock[0] += 61
    assert provider.maybe_reload() is False
    assert provider.semantic_status() == {"state": "ready", "model": "fake", "rows": 3}


def test_maybe_reload_before_the_embedder_is_ready_does_nothing(env):
    provider, index_dir, _ = env
    _write(index_dir, 3)
    assert provider.maybe_reload(force=True) is False
    assert provider.semantic_status()["state"] == "disabled"


def test_initialise_failure_leaves_the_provider_lexical_only(env):
    provider, _, _ = env
    provider._embedder_factory = lambda s, card: (_ for _ in ()).throw(RuntimeError("model missing"))
    provider.initialise()
    assert provider.semantic_status()["state"] == "disabled"
