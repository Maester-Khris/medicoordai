import json
import os
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import onnxruntime as ort
import pytest

from graph.semantic.embedder import (
    OnnxEmbedder,
    build_session_options,
    cls_pool,
    l2_normalize,
    mean_pool,
)
from graph.semantic.settings import SemanticSettings, load_settings

ENV = {"SEMANTIC_MODEL_DIR": "/models/m", "SEMANTIC_INDEX_DIR": "/idx"}


def _settings(**kw):
    base = dict(model_dir=Path("/models/m"), index_dir=Path("/idx"), score_threshold=0.5, gap_margin=0.02, lay_rule="confirmed")
    base.update(kw)
    return SemanticSettings(**base)


def test_session_options_pin_threads_and_disable_spinning():
    opts = build_session_options(1)
    assert opts.intra_op_num_threads == 1 and opts.inter_op_num_threads == 1
    assert opts.execution_mode == ort.ExecutionMode.ORT_SEQUENTIAL
    assert opts.get_session_config_entry("session.intra_op.allow_spinning") == "0"
    assert build_session_options(2, allow_spinning=True).get_session_config_entry("session.intra_op.allow_spinning") == "1"


def test_default_threads_is_one_and_zero_is_rejected():
    s = load_settings(ENV)
    assert (s.threads, s.deadline_ms, s.top_n, s.lay_rule) == (1, 250, 20, "confirmed")
    assert s.model_dir == Path("/models/m") and s.index_dir == Path("/idx")
    assert load_settings({**ENV, "EMBED_THREADS": "2", "EMBED_DEADLINE_MS": "300", "SEMANTIC_LAY_RULE": "approved"}).threads == 2
    with pytest.raises(ValueError):
        load_settings({**ENV, "EMBED_THREADS": "0"})
    with pytest.raises(ValueError):
        load_settings({"SEMANTIC_INDEX_DIR": "/idx"})  # model dir missing


def test_pooling_and_normalisation_match_reference_vectors():
    hidden = np.array([[1.0, 2.0], [3.0, 4.0], [100.0, 100.0]])
    mask = np.array([1, 1, 0])
    assert np.allclose(mean_pool(hidden, mask), [2.0, 3.0])  # the padded position is ignored
    assert np.allclose(cls_pool(hidden), [1.0, 2.0])
    v = l2_normalize(np.array([3.0, 4.0]))
    assert np.allclose(v, [0.6, 0.8]) and np.isclose(np.linalg.norm(v), 1.0)
    assert np.allclose(l2_normalize(np.zeros(3)), np.zeros(3))  # no NaN for a zero vector


class FakeTokenizer:
    def __init__(self):
        self.max_length = None

    def enable_truncation(self, max_length):
        self.max_length = max_length

    def encode(self, text):
        n = max(1, len(text.split()))
        return SimpleNamespace(ids=list(range(n)), attention_mask=[1] * n, type_ids=[0] * n)


class FakeSession:
    def __init__(self, dim=4, input_names=("input_ids", "attention_mask")):
        self.dim, self.calls = dim, []
        self._inputs = [SimpleNamespace(name=n) for n in input_names]

    def get_inputs(self):
        return self._inputs

    def run(self, _outputs, feeds):
        self.calls.append(feeds)
        n = feeds["input_ids"].shape[1]
        hidden = np.tile(np.arange(1, self.dim + 1, dtype=np.float32), (1, n, 1))
        return [hidden]


def _embedder(session=None, pooling="mean", prefix="", **kw):
    return OnnxEmbedder(Path("/models/m"), _settings(**kw), pooling=pooling, prefix=prefix, session=session or FakeSession(),
                        tokenizer=FakeTokenizer())


def test_embedder_not_ready_until_warm_up_completes():
    session = FakeSession()
    e = _embedder(session)
    assert e.ready is False and session.calls == []
    e.warm_up()
    assert e.ready is True and e.dim == 4 and len(session.calls) >= 4


def test_embed_returns_a_unit_float32_vector_and_feeds_only_declared_inputs():
    session = FakeSession(input_names=("input_ids", "attention_mask", "token_type_ids"))
    e = _embedder(session, prefix="query: ")
    v = e.embed("my nose is blocked")
    assert v.dtype == np.float32 and v.shape == (4,) and np.isclose(np.linalg.norm(v), 1.0)
    feeds = session.calls[0]
    assert set(feeds) == {"input_ids", "attention_mask", "token_type_ids"} and feeds["input_ids"].dtype == np.int64
    assert feeds["input_ids"].shape[1] == len("query: my nose is blocked".split())  # the prefix reaches the model


def test_empty_text_raises_ValueError_so_callers_can_skip():
    e = _embedder()
    for text in ("", "   ", "\n\t"):
        with pytest.raises(ValueError):
            e.embed(text)


def test_constructor_sets_tokenizer_threading_env(monkeypatch):
    monkeypatch.delenv("RAYON_NUM_THREADS", raising=False)
    monkeypatch.delenv("TOKENIZERS_PARALLELISM", raising=False)
    _embedder(threads=2)
    assert os.environ["RAYON_NUM_THREADS"] == "2" and os.environ["TOKENIZERS_PARALLELISM"] == "false"


@pytest.mark.integration
def test_onnx_model_matches_torch_reference():
    model_dir = os.environ.get("SEMANTIC_MODEL_DIR")
    if not model_dir or not (Path(model_dir) / "reference.json").exists():
        pytest.skip("SEMANTIC_MODEL_DIR with reference.json (written by export_onnx) not available")
    ref = json.loads((Path(model_dir) / "reference.json").read_text())
    e = OnnxEmbedder(Path(model_dir), _settings(model_dir=Path(model_dir)), pooling=ref["pooling"], prefix=ref["prefix"],
                     max_len=ref["max_len"])
    for item in ref["items"]:
        got, want = e.embed(item["text"]), l2_normalize(np.array(item["vector"], dtype=np.float32))
        assert float(got @ want) >= 0.99
