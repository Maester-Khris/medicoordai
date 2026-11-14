import hashlib
import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from graph.semantic import embedder as emb
from graph.semantic.settings import SemanticSettings, load_settings

GOOD = b"onnx-model-bytes"
GOOD_SHA = hashlib.sha256(GOOD).hexdigest()


def _settings(tmp_path: Path, sha: str | None) -> SemanticSettings:
    return SemanticSettings(model_dir=tmp_path, index_dir=tmp_path, score_threshold=0.5, gap_margin=0.02,
                            lay_rule="confirmed", model_sha256=sha)


def test_matching_hash_passes(tmp_path):
    f = tmp_path / "model.onnx"; f.write_bytes(GOOD)
    emb.verify_model_file(f, GOOD_SHA)


def test_a_modified_file_is_refused(tmp_path):
    f = tmp_path / "model.onnx"; f.write_bytes(GOOD + b"x")
    with pytest.raises(emb.ModelIntegrityError):
        emb.verify_model_file(f, GOOD_SHA)


def test_the_comparison_ignores_case(tmp_path):
    f = tmp_path / "model.onnx"; f.write_bytes(GOOD)
    emb.verify_model_file(f, GOOD_SHA.upper())


def test_unpinned_hash_loads_with_a_warning(tmp_path, caplog):
    f = tmp_path / "model.onnx"; f.write_bytes(GOOD)
    with caplog.at_level(logging.WARNING, logger="graph.semantic.embedder"):
        emb.verify_model_file(f, None)
    assert [r for r in caplog.records if r.message == "semantic_model_hash_unpinned"]


def test_the_embedder_never_opens_a_tampered_model(tmp_path):
    (tmp_path / "model.onnx").write_bytes(GOOD + b"x")
    with patch.object(emb.ort, "InferenceSession") as session, patch.object(emb, "Tokenizer"):
        with pytest.raises(emb.ModelIntegrityError):
            emb.OnnxEmbedder(tmp_path, _settings(tmp_path, GOOD_SHA), pooling="mean", prefix="")
    session.assert_not_called()


def test_the_embedder_opens_a_model_that_matches(tmp_path):
    (tmp_path / "model.onnx").write_bytes(GOOD)
    with patch.object(emb.ort, "InferenceSession", return_value=MagicMock()) as session, patch.object(emb, "Tokenizer"):
        emb.OnnxEmbedder(tmp_path, _settings(tmp_path, GOOD_SHA), pooling="mean", prefix="")
    session.assert_called_once()


def test_the_int8_file_is_the_one_checked(tmp_path):
    (tmp_path / "model.onnx").write_bytes(b"other")
    (tmp_path / "model.int8.onnx").write_bytes(GOOD)
    with patch.object(emb.ort, "InferenceSession", return_value=MagicMock()), patch.object(emb, "Tokenizer"):
        emb.OnnxEmbedder(tmp_path, _settings(tmp_path, GOOD_SHA), pooling="mean", prefix="")  # no error: int8 matches


def _env(**extra: str) -> dict[str, str]:
    return {"SEMANTIC_MODEL_DIR": "/m", "SEMANTIC_INDEX_DIR": "/i", **extra}


def test_settings_read_the_pinned_hash():
    assert load_settings(_env(SEMANTIC_MODEL_SHA256=GOOD_SHA.upper())).model_sha256 == GOOD_SHA
    assert load_settings(_env()).model_sha256 is None


@pytest.mark.parametrize("bad", ["abc", "z" * 64, GOOD_SHA + "0"])
def test_settings_reject_a_malformed_hash(bad):
    with pytest.raises(ValueError):
        load_settings(_env(SEMANTIC_MODEL_SHA256=bad))
