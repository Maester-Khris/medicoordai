import hashlib
import logging
import os
from pathlib import Path
from typing import Any, Optional, Protocol, runtime_checkable

import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer

from graph.semantic.settings import SemanticSettings

logger = logging.getLogger(__name__)


class ModelIntegrityError(RuntimeError):
    """The model file on disk is not the one that was pinned."""


def verify_model_file(path: Path, expected_sha256: str | None) -> None:
    """Refuse a model file whose sha256 differs from the pinned value.

    The pin comes from the environment (SEMANTIC_MODEL_SHA256), not from a file next to the model:
    anyone who can replace the model on the volume could replace a sidecar file too.
    Unpinned: load and warn, so existing deploys keep working until the pin is set.
    """
    if not expected_sha256:
        logger.warning("semantic_model_hash_unpinned")
        return
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    if digest.hexdigest() != expected_sha256.lower():
        raise ModelIntegrityError(f"{Path(path).name} does not match the pinned sha256")


@runtime_checkable
class Embedder(Protocol):
    name: str
    dim: int
    ready: bool

    def embed(self, text: str) -> np.ndarray:
        ...


def build_session_options(threads: int, allow_spinning: bool = False) -> ort.SessionOptions:
    opts = ort.SessionOptions()
    opts.intra_op_num_threads = threads
    opts.inter_op_num_threads = 1
    opts.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    # An idle spinning worker burns CPU on a shared box and steals it from the API.
    opts.add_session_config_entry(
        "session.intra_op.allow_spinning", "1" if allow_spinning else "0"
    )
    return opts


def mean_pool(hidden: np.ndarray, mask: np.ndarray) -> np.ndarray:
    mask_expanded = np.asarray(mask, dtype=np.float32).reshape(-1, 1)
    sum_mask = np.sum(mask_expanded, axis=0)
    if np.all(sum_mask == 0):
        return np.zeros(hidden.shape[1], dtype=np.float32)
    sum_hidden = np.sum(hidden * mask_expanded, axis=0)
    return (sum_hidden / sum_mask).astype(np.float32)


def cls_pool(hidden: np.ndarray) -> np.ndarray:
    return np.asarray(hidden[0], dtype=np.float32)


def l2_normalize(v: np.ndarray) -> np.ndarray:
    v_arr = np.asarray(v, dtype=np.float32)
    norm = float(np.linalg.norm(v_arr))
    if norm <= 0.0 or np.isnan(norm):
        return np.zeros_like(v_arr, dtype=np.float32)
    return (v_arr / norm).astype(np.float32)


class OnnxEmbedder:
    def __init__(
        self,
        model_dir: Path,
        settings: SemanticSettings,
        pooling: str,
        prefix: str,
        max_len: int = 64,
        *,
        session: Optional[Any] = None,
        tokenizer: Optional[Any] = None,
    ) -> None:
        if pooling not in ("mean", "cls"):
            raise ValueError(f"pooling must be 'mean' or 'cls', got {pooling!r}")

        # The tokenizers library starts its own thread pool; unbounded it would defeat the thread cap.
        os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
        os.environ.setdefault("RAYON_NUM_THREADS", str(settings.threads))

        model_dir = Path(model_dir)

        if session is None:
            # The int8 file is preferred; an fp32 "model.onnx" is the supported fallback for models
            # (BioLORD) that lose too much accuracy when quantized.
            int8_path = model_dir / "model.int8.onnx"
            model_path = str(int8_path if int8_path.exists() else model_dir / "model.onnx")
            verify_model_file(Path(model_path), settings.model_sha256)
            session = ort.InferenceSession(
                model_path,
                sess_options=build_session_options(settings.threads),
                providers=["CPUExecutionProvider"],
            )

        if tokenizer is None:
            tokenizer = Tokenizer.from_file(str(model_dir / "tokenizer.json"))

        tokenizer.enable_truncation(max_len)

        self.model_dir: Path = model_dir
        self.settings: SemanticSettings = settings
        self.pooling: str = pooling
        self.prefix: str = prefix
        self.max_len: int = max_len
        self.session: Any = session
        self.tokenizer: Any = tokenizer

        self.name: str = model_dir.name
        self.dim: int = 0
        self.ready: bool = False

    def embed(self, text: str) -> np.ndarray:
        stripped = text.strip()
        if not stripped:
            raise ValueError("empty text")

        full_text = self.prefix + stripped
        encoding = self.tokenizer.encode(full_text)

        declared_inputs = {inp.name for inp in self.session.get_inputs()}
        type_ids = getattr(encoding, "type_ids", None)
        if type_ids is None:
            type_ids = [0] * len(encoding.ids)

        all_feeds = {
            "input_ids": np.array([encoding.ids], dtype=np.int64),
            "attention_mask": np.array([encoding.attention_mask], dtype=np.int64),
            "token_type_ids": np.array([type_ids], dtype=np.int64),
        }
        feeds = {k: v for k, v in all_feeds.items() if k in declared_inputs}

        outputs = self.session.run(None, feeds)
        hidden = outputs[0][0]
        self.dim = int(hidden.shape[1])

        if self.pooling == "mean":
            mask = np.array(encoding.attention_mask, dtype=np.int64)
            pooled = mean_pool(hidden, mask)
        else:
            pooled = cls_pool(hidden)

        return l2_normalize(pooled)

    def warm_up(self) -> None:
        # First-call allocation and graph optimisation cost hundreds of ms;
        # running warm-up inferences ensures subsequent request latency is predictable.
        sample_texts = [
            "patient reports mild headache today",
            "patient presents with a persistent cough and mild fever for three days",
            (
                "the doctor recommended further clinical examination and standard diagnostic "
                "laboratory testing including complete blood count and metabolic panel to evaluate "
                "possible chronic fatigue symptoms and vitamin deficiency"
            ),
            (
                "clinical evaluation of severe abdominal pain with nausea vomiting and localized "
                "tenderness in the right lower quadrant indicates possible acute appendicitis "
                "requiring urgent surgical consultation and diagnostic ultrasound imaging to confirm "
                "inflammation before determining appropriate surgical intervention and post-operative "
                "recovery protocol"
            ),
            "patient reports mild headache today",
        ]
        for text in sample_texts:
            self.embed(text)
        self.ready = True
