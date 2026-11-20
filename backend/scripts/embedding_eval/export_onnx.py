"""Offline ONNX export, CPU-matched quantization, and parity checking.

Import cost is kept minimal: only stdlib + numpy at top level.
Heavy dependencies (torch, transformers, onnxruntime) are imported inside
the functions that need them so unit tests stay light.
"""
from __future__ import annotations

import argparse
import hashlib
import inspect
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

import numpy as np

# ---------------------------------------------------------------------------
# 20 fixed everyday symptom sentences used for reference.json
# ---------------------------------------------------------------------------
_REFERENCE_SENTENCES: list[str] = [
    "I have a headache and feel dizzy",
    "My chest feels tight and I am short of breath",
    "I have had a fever for three days",
    "My stomach hurts and I feel nauseous",
    "I have a sore throat and difficulty swallowing",
    "I feel very tired and have no energy",
    "My lower back is aching constantly",
    "I have a rash on my arm that is itchy",
    "I cannot stop coughing and my nose is runny",
    "My knee is swollen and painful to walk on",
    "I have been vomiting since last night",
    "My vision is blurry and my eyes hurt",
    "I feel anxious and my heart is racing",
    "I have pain when I urinate",
    "My ear hurts and I hear a ringing sound",
    "I have swollen lymph nodes in my neck",
    "I feel numbness in my left arm",
    "I have been having severe headaches with light sensitivity",
    "My jaw hurts and I have difficulty opening my mouth",
    "I feel bloated and have not had a bowel movement in days",
]


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class QuantConfig:
    weight_type: str
    reduce_range: bool


@dataclass(frozen=True)
class ParityReport:
    min_cosine: float
    mean_cosine: float


# ---------------------------------------------------------------------------
# CPU flag helpers
# ---------------------------------------------------------------------------

def read_cpu_flags(cpuinfo_path: str = "/proc/cpuinfo") -> set[str]:
    """Return tokens from the first 'flags' line in cpuinfo.

    Missing or unreadable file → empty set (safe unsigned fallback).
    """
    try:
        with open(cpuinfo_path) as fh:
            for line in fh:
                if line.startswith("flags"):
                    # e.g. "flags\t\t: fpu avx2 avx512_vnni sse4_2"
                    _, _, rest = line.partition(":")
                    return set(rest.split())
    except OSError:
        pass
    return set()


def choose_quantization(cpu_flags: set[str]) -> QuantConfig:
    """Pick the safest quantization scheme for the detected CPU.

    Dynamic quantization with *signed* weights (QInt8) is only safe and fast
    where VNNI (Vector Neural Network Instructions) exists.  On older x86 the
    u8s8 matmul kernels can saturate; the unsigned + reduce_range combination
    avoids that bug at the cost of a small accuracy trade-off.
    """
    if "avx512_vnni" in cpu_flags or "avx_vnni" in cpu_flags:
        # VNNI present → signed weights are safe, no range reduction needed.
        return QuantConfig(weight_type="QInt8", reduce_range=False)
    # Older CPU → unsigned weights + reduce_range to avoid u8s8 saturation bug.
    return QuantConfig(weight_type="QUInt8", reduce_range=True)


# ---------------------------------------------------------------------------
# Cosine similarity helpers
# ---------------------------------------------------------------------------

def min_cosine(a: np.ndarray, b: np.ndarray) -> float:
    """Minimum cosine similarity over paired rows of 2-D arrays."""
    # Defensive normalisation
    def _norm(x: np.ndarray) -> np.ndarray:
        norms = np.linalg.norm(x, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1.0, norms)
        return x / norms

    a_n = _norm(np.asarray(a, dtype=np.float64))
    b_n = _norm(np.asarray(b, dtype=np.float64))
    sims = np.sum(a_n * b_n, axis=1)
    return float(np.min(sims))


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def _torch_encode(
    tokenizer: "Any",
    model: "Any",
    texts: list[str],
    pool: str,
    max_len: int,
    prefix: str,
) -> "np.ndarray":
    """Encode texts with torch (fp32), apply prefix, pool, L2-normalise."""
    import torch

    prefixed = [prefix + t for t in texts]
    enc = tokenizer(
        prefixed,
        padding=True,
        truncation=True,
        max_length=max_len,
        return_tensors="pt",
    )
    with torch.no_grad():
        hidden = model(**enc).last_hidden_state  # (B, S, D)

    if pool == "cls":
        vec = hidden[:, 0]
    else:
        mask = enc["attention_mask"].unsqueeze(-1).float()
        vec = (hidden * mask).sum(1) / mask.sum(1).clamp(min=1e-9)

    return torch.nn.functional.normalize(vec, dim=-1).numpy()


def export(
    model_key: str,
    out_dir: Path,
    quant: QuantConfig | None,
    prefix_name: str | None = None,
) -> None:
    """Export *model_key* to out_dir as a quantised ONNX model.

    Steps:
    1. Load tokenizer + model from local HF cache (no token).
    2. Export fp32 ONNX (dynamo=False, opset 17).
    3. Dynamic-quantize to int8.
    4. Delete fp32 artifact.
    5. Save tokenizer.json (HF fast tokenizer backend).
    6. Write reference.json (20 fixed sentences + fp32 torch vectors).
    7. Write export.json (provenance / metadata).
    """
    import torch
    from transformers import AutoModel, AutoTokenizer

    # Lazy import so top-level import stays stdlib+numpy only.
    from scripts.embedding_eval.embed_eval import MODELS  # noqa: PLC0415

    cfg = MODELS[model_key]
    repo: str = cfg["repo"]
    pool: str = cfg["pool"]
    max_len: int = cfg["max_len"]
    prefixes: dict[str, str] = cfg["prefixes"]

    resolved_prefix_name: str = prefix_name if prefix_name is not None else next(iter(prefixes))
    prefix: str = prefixes[resolved_prefix_name]

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # --- Load model & tokenizer ------------------------------------------------
    tokenizer = AutoTokenizer.from_pretrained(repo)
    model = AutoModel.from_pretrained(repo, attn_implementation="eager").eval().float()

    # --- Determine tokenizer output keys present for this model ----------------
    sample_enc = tokenizer("test", return_tensors="pt")
    input_names: list[str] = []
    for name in ("input_ids", "attention_mask", "token_type_ids"):
        if name in sample_enc:
            input_names.append(name)

    # --- ONNX wrapper ----------------------------------------------------------
    class _EncoderWrapper(torch.nn.Module):
        def __init__(self, inner: torch.nn.Module, names: list[str]) -> None:
            super().__init__()
            self._inner = inner
            self._names = names

        def forward(self, *args: torch.Tensor) -> torch.Tensor:
            feed = {n: v for n, v in zip(self._names, args)}
            return self._inner(**feed).last_hidden_state

    wrapper = _EncoderWrapper(model, input_names)

    # Example inputs: a real padded batch, so the traced graph sees a realistic mask.
    sample = tokenizer(
        _REFERENCE_SENTENCES[:4], padding=True, truncation=True, max_length=max_len, return_tensors="pt"
    )
    example_inputs = tuple(sample[n] for n in input_names)
    batch_dim = torch.export.Dim("batch", min=1, max=64)
    seq_dim = torch.export.Dim("sequence", min=2, max=max_len)
    dynamic_shapes = {"args": tuple({0: batch_dim, 1: seq_dim} for _ in input_names)}  # the wrapper takes *args

    fp32_path = out_dir / "model.fp32.onnx"
    int8_path = out_dir / "model.int8.onnx"
    final_path = int8_path if quant is not None else out_dir / "model.onnx"

    # dynamo=True (torch.export) on purpose: the legacy tracer baked parts of MPNet's relative
    # position handling into the graph and the fp32 ONNX only reached cosine 0.94 against torch for
    # BioLORD; the torch.export path reproduces torch to 1e-7.
    onnx_program = torch.onnx.export(
        wrapper,
        example_inputs,
        dynamo=True,
        dynamic_shapes=dynamic_shapes,
        input_names=input_names,
        output_names=["last_hidden_state"],
    )
    onnx_program.save(str(fp32_path))

    # --- Quantize (or keep fp32) -----------------------------------------------
    if quant is None:
        # BioLORD loses too much to dynamic int8 (cosine 0.67-0.88 against fp32), so fp32 ONNX is a
        # supported output: bigger and slower, but exact.
        fp32_path.replace(final_path)
    else:
        from onnxruntime.quantization import QuantType, quantize_dynamic

        weight_type = QuantType.QInt8 if quant.weight_type == "QInt8" else QuantType.QUInt8
        sig = inspect.signature(quantize_dynamic)
        quant_kwargs: dict = dict(weight_type=weight_type)
        if "reduce_range" in sig.parameters:
            quant_kwargs["reduce_range"] = quant.reduce_range
        else:
            quant_kwargs["extra_options"] = {"ReduceRange": quant.reduce_range}
        if quant.reduce_range:
            quant_kwargs.setdefault("extra_options", {})
            quant_kwargs["extra_options"]["ActivationSymmetric"] = False
        quantize_dynamic(str(fp32_path), str(final_path), **quant_kwargs)
        fp32_path.unlink()

    # --- Save tokenizer --------------------------------------------------------
    tok_path = out_dir / "tokenizer.json"
    tokenizer.backend_tokenizer.save(str(tok_path))

    # --- reference.json --------------------------------------------------------
    ref_vecs = _torch_encode(tokenizer, model, _REFERENCE_SENTENCES, pool, max_len, prefix)
    reference = {
        "pooling": pool,
        "prefix": prefix,
        "max_len": max_len,
        "items": [
            {"text": t, "vector": v.tolist()}
            for t, v in zip(_REFERENCE_SENTENCES, ref_vecs)
        ],
    }
    (out_dir / "reference.json").write_text(json.dumps(reference, indent=1))

    # --- export.json -----------------------------------------------------------
    import onnxruntime as ort

    model_sha = hashlib.sha256(final_path.read_bytes()).hexdigest()
    tok_sha = hashlib.sha256(tok_path.read_bytes()).hexdigest()

    # Infer hidden dim from the model config
    hidden_size = model.config.hidden_size

    # CPU flags filtered to interesting substrings
    all_flags = read_cpu_flags()
    keep_patterns = ("avx", "vnni", "sse4", "amx")
    cpu_flags_filtered = sorted(
        f for f in all_flags if any(p in f for p in keep_patterns)
    )

    export_meta = {
        "model_key": model_key,
        "repo": repo,
        "pooling": pool,
        "prefix": prefix,
        "prefix_name": resolved_prefix_name,
        "max_len": max_len,
        "dim": hidden_size,
        "model_sha256": model_sha,
        "tokenizer_sha256": tok_sha,
        "model_file": final_path.name,
        "quantization": (
            None if quant is None
            else {"weight_type": quant.weight_type, "reduce_range": quant.reduce_range}
        ),
        "cpu_flags": cpu_flags_filtered,
        "torch_version": torch.__version__,
        "onnxruntime_version": ort.__version__,
        "exported_at": datetime.now(timezone.utc).isoformat(),
    }
    (out_dir / "export.json").write_text(json.dumps(export_meta, indent=1))


# ---------------------------------------------------------------------------
# Parity
# ---------------------------------------------------------------------------

def parity(
    model_key: str,
    out_dir: Path,
    queries: Sequence[str],
) -> ParityReport:
    """Compare fp32 torch vectors vs int8 OnnxEmbedder vectors.

    Returns ParityReport(min_cosine, mean_cosine).  The hit@5 comparison is
    done end-to-end by eval_index.py; this function only checks vector fidelity.
    """
    import torch
    from transformers import AutoModel, AutoTokenizer

    from scripts.embedding_eval.embed_eval import MODELS  # noqa: PLC0415

    out_dir = Path(out_dir)
    export_meta = json.loads((out_dir / "export.json").read_text())
    pool: str = export_meta["pooling"]
    prefix: str = export_meta["prefix"]
    max_len: int = export_meta["max_len"]

    cfg = MODELS[model_key]
    repo: str = cfg["repo"]

    # --- Torch fp32 embeddings ------------------------------------------------
    tokenizer = AutoTokenizer.from_pretrained(repo)
    model = AutoModel.from_pretrained(repo, attn_implementation="eager").eval().float()
    torch_vecs = _torch_encode(tokenizer, model, list(queries), pool, max_len, prefix)

    # --- OnnxEmbedder embeddings ----------------------------------------------
    from graph.semantic.embedder import OnnxEmbedder
    from graph.semantic.settings import SemanticSettings

    settings = SemanticSettings(
        model_dir=out_dir,
        index_dir=out_dir,
        score_threshold=0.5,
        gap_margin=0.02,
        lay_rule="confirmed",
    )
    embedder = OnnxEmbedder(
        model_dir=out_dir,
        settings=settings,
        pooling=pool,
        prefix=prefix,
        max_len=max_len,
    )

    onnx_vecs = np.stack([embedder.embed(q) for q in queries])

    # --- Parity metrics -------------------------------------------------------
    sims = np.sum(torch_vecs * onnx_vecs, axis=1)
    return ParityReport(
        min_cosine=float(np.min(sims)),
        mean_cosine=float(np.mean(sims)),
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    here = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(
        description="Export a model to ONNX and check parity with the int8 OnnxEmbedder."
    )
    parser.add_argument(
        "--model",
        required=True,
        help="A key from MODELS in embed_eval.py (e.g. bge_small, biolord).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output directory (default: results/onnx/<model> next to this file).",
    )
    parser.add_argument(
        "--prefix-name",
        default=None,
        help="Prefix key from the model's prefixes dict.",
    )
    parser.add_argument(
        "--queries",
        type=Path,
        default=None,
        help=(
            "Optional JSON file of query objects with a 'message' key. "
            "Default: the 20 reference sentences."
        ),
    )
    parser.add_argument(
        "--cpuinfo",
        default="/proc/cpuinfo",
        help="Path to cpuinfo file (default /proc/cpuinfo). Pass a saved file to export for a remote CPU.",
    )
    parser.add_argument(
        "--force-quant",
        choices=["QInt8", "QUInt8", "none"],
        default=None,
        help="Override automatic quantization choice; 'none' keeps the exact fp32 ONNX (model.onnx).",
    )
    return parser


def main() -> None:
    from scripts.embedding_eval.embed_eval import MODELS  # noqa: PLC0415

    parser = _build_parser()
    args = parser.parse_args()

    here = Path(__file__).resolve().parent

    if args.out is None:
        out_dir = here / "results" / "onnx" / args.model
    else:
        out_dir = args.out

    # Determine quantization
    if args.force_quant is not None:
        if args.force_quant == "none":
            quant = None
        elif args.force_quant == "QInt8":
            quant = QuantConfig(weight_type="QInt8", reduce_range=False)
        else:
            quant = QuantConfig(weight_type="QUInt8", reduce_range=True)
    else:
        cpu_flags = read_cpu_flags(args.cpuinfo)
        quant = choose_quantization(cpu_flags)

    print("Quantization: none (fp32)" if quant is None else f"Quantization: {quant.weight_type}, reduce_range={quant.reduce_range}")

    export(args.model, out_dir, quant, prefix_name=args.prefix_name)
    print(f"Exported to: {out_dir}")

    # Determine query texts
    if args.queries is not None:
        raw = json.loads(args.queries.read_text())
        query_texts = [item["message"] for item in raw]
    else:
        query_texts = _REFERENCE_SENTENCES

    report = parity(args.model, out_dir, query_texts)
    print(f"Parity: min_cosine={report.min_cosine:.4f}, mean_cosine={report.mean_cosine:.4f}")


if __name__ == "__main__":
    main()
