"""Embedder latency, memory and capacity benchmark.

Designed to run as a plain script on a small Railway service:
    python bench_embedder.py --model-dir /data/model

Imports: stdlib, numpy, graph.semantic.embedder, graph.semantic.settings only.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from itertools import cycle
from pathlib import Path
from typing import Optional, Sequence

import numpy as np

from graph.semantic.embedder import OnnxEmbedder
from graph.semantic.settings import SemanticSettings


# ---------------------------------------------------------------------------
# Pure-stat helpers
# ---------------------------------------------------------------------------

def latency_stats(samples_ms: Sequence[float]) -> dict[str, float]:
    """Return p50/p95/p99/max/mean/n for *samples_ms* (milliseconds).

    Uses numpy's default linear interpolation for percentiles.
    Raises ValueError on empty input.
    """
    if len(samples_ms) == 0:
        raise ValueError("samples_ms must not be empty")
    arr = np.asarray(samples_ms, dtype=np.float64)
    return {
        "p50": float(np.percentile(arr, 50)),
        "p95": float(np.percentile(arr, 95)),
        "p99": float(np.percentile(arr, 99)),
        "max": float(arr.max()),
        "mean": float(arr.mean()),
        "n": int(len(arr)),
    }


def capacity_estimate(
    added_ms: float,
    base_cpu_ms: float = 16.0,
    base_capacity: float = 35.0,
) -> float:
    """Estimate turns/s after adding *added_ms* of CPU per API turn.

    Sprint 22 model: one API turn costs ~16 ms of CPU and the box handled
    ~35 turns/s.  Extra embedding CPU per turn lowers capacity proportionally.
    """
    return base_capacity * base_cpu_ms / (base_cpu_ms + added_ms)


def parse_proc_status(text: str) -> dict:
    """Parse /proc/self/status text and return rss_mb and threads.

    Returns {"rss_mb": float | None, "threads": int | None}.
    """
    rss_mb: Optional[float] = None
    threads: Optional[int] = None

    for line in text.splitlines():
        m = re.match(r"VmRSS:\s+(\d+)\s+kB", line)
        if m:
            rss_mb = int(m.group(1)) / 1024

        m = re.match(r"Threads:\s+(\d+)", line)
        if m:
            threads = int(m.group(1))

    return {"rss_mb": rss_mb, "threads": threads}


# ---------------------------------------------------------------------------
# Single-process benchmark (called in a fresh subprocess)
# ---------------------------------------------------------------------------

_BUILTIN_TEXTS = [
    "patient reports mild headache today",
    "patient presents with persistent cough and mild fever",
    "doctor recommended laboratory testing for possible vitamin deficiency",
    "clinical evaluation of severe abdominal pain indicates possible appendicitis",
    "follow-up appointment scheduled for next week to review test results",
]


def bench(model_dir: Path, threads: int, calls: int = 200) -> dict:
    """Benchmark *model_dir* at *threads* ONNX intra-op threads.

    Returns a dict with timing, memory and capacity metrics.
    """
    settings = SemanticSettings(
        model_dir=model_dir,
        index_dir=model_dir,
        score_threshold=0.5,
        gap_margin=0.02,
        lay_rule="confirmed",
        threads=threads,
    )

    # Read export.json for pooling/prefix/max_len
    export_path = model_dir / "export.json"
    with open(export_path) as f:
        export = json.load(f)
    pooling: str = export["pooling"]
    prefix: str = export.get("prefix", "")
    max_len: int = export.get("max_len", 64)

    # Reference texts for steady-state calls
    ref_path = model_dir / "reference.json"
    if ref_path.exists():
        with open(ref_path) as f:
            ref_data = json.load(f)
        # reference.json is {"pooling", "prefix", "max_len", "items": [{"text", "vector"}]}
        ref_items = ref_data["items"] if isinstance(ref_data, dict) else ref_data
        texts = [item["text"] for item in ref_items] or _BUILTIN_TEXTS
    else:
        texts = _BUILTIN_TEXTS

    text_cycle = cycle(texts)

    # --- Load time ---
    t0 = time.perf_counter()
    embedder = OnnxEmbedder(
        model_dir=model_dir,
        settings=settings,
        pooling=pooling,
        prefix=prefix,
        max_len=max_len,
    )
    load_ms = (time.perf_counter() - t0) * 1000.0

    # --- First call latency (before warm_up) ---
    t0 = time.perf_counter()
    embedder.embed(next(text_cycle))
    first_call_ms = (time.perf_counter() - t0) * 1000.0

    # --- Warm-up ---
    t0 = time.perf_counter()
    embedder.warm_up()
    warm_up_ms = (time.perf_counter() - t0) * 1000.0

    # --- Steady-state calls ---
    samples: list[float] = []
    for _ in range(calls):
        t0 = time.perf_counter()
        embedder.embed(next(text_cycle))
        samples.append((time.perf_counter() - t0) * 1000.0)

    steady = latency_stats(samples)

    # --- Memory / thread count ---
    rss_mb: Optional[float] = None
    process_threads: Optional[int] = None
    try:
        with open("/proc/self/status") as f:
            proc_text = f.read()
        parsed = parse_proc_status(proc_text)
        rss_mb = parsed["rss_mb"]
        process_threads = parsed["threads"]
    except FileNotFoundError:
        pass

    return {
        "model": model_dir.name,
        "threads": threads,
        "load_ms": load_ms,
        "first_call_ms": first_call_ms,
        "warm_up_ms": warm_up_ms,
        "steady": steady,
        "rss_mb": rss_mb,
        "process_threads": process_threads,
        "capacity_turns_per_s": capacity_estimate(steady["p50"]),
        "capacity_at_p95": capacity_estimate(steady["p95"]),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _run_single(args: argparse.Namespace) -> None:
    """Internal --single mode: run bench() and print one JSON line."""
    model_dir = Path(args.single_model_dir)
    threads = int(args.single_threads)
    calls = args.calls
    result = bench(model_dir, threads, calls)
    print(json.dumps(result))


def _print_table(results: list[dict]) -> None:
    header = (
        f"{'model':>20} {'thr':>3} {'load':>8} {'1st':>8} "
        f"{'p50':>8} {'p95':>8} {'p99':>8} {'RSS MB':>8} {'cap t/s':>8}"
    )
    print(header)
    print("-" * len(header))
    for r in results:
        s = r["steady"]
        rss = f"{r['rss_mb']:.1f}" if r["rss_mb"] is not None else "N/A"
        print(
            f"{r['model']:>20} {r['threads']:>3} "
            f"{r['load_ms']:>8.1f} {r['first_call_ms']:>8.1f} "
            f"{s['p50']:>8.1f} {s['p95']:>8.1f} {s['p99']:>8.1f} "
            f"{rss:>8} {r['capacity_turns_per_s']:>8.2f}"
        )
    print()
    print("Budgets: p95 added latency <= 120 ms, capacity >= 15 turns/s")


def _parse_threads(raw: str) -> list[int]:
    return [int(t.strip()) for t in raw.split(",") if t.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(description="OnnxEmbedder latency benchmark")
    parser.add_argument("--model-dir", dest="model_dirs", action="append", metavar="DIR")
    parser.add_argument("--threads", default="1,2")
    parser.add_argument("--calls", type=int, default=200)
    parser.add_argument("--out", default=None)

    # Internal flag: run a single (model, threads) combo in this process
    parser.add_argument("--single", dest="single_model_dir", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--single-threads", dest="single_threads", default=None, help=argparse.SUPPRESS)

    args = parser.parse_args()

    # Internal single-run mode
    if args.single_model_dir is not None:
        _run_single(args)
        return

    if not args.model_dirs:
        parser.error("at least one --model-dir is required")

    thread_list = _parse_threads(args.threads)
    results: list[dict] = []

    for model_dir_str in args.model_dirs:
        for t in thread_list:
            env = os.environ.copy()
            env["RAYON_NUM_THREADS"] = str(t)
            env["EMBED_THREADS"] = str(t)

            cmd = [
                sys.executable,
                __file__,
                "--single", model_dir_str,
                "--single-threads", str(t),
                "--calls", str(args.calls),
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True, env=env)
            if proc.returncode != 0:
                print(
                    f"ERROR running bench for model={model_dir_str} threads={t}:\n{proc.stderr}",
                    file=sys.stderr,
                )
                continue
            line = proc.stdout.strip().splitlines()[-1]
            result = json.loads(line)
            results.append(result)

    _print_table(results)

    if args.out:
        out_path = Path(args.out)
        out_path.write_text(json.dumps(results, indent=2))
        print(f"\nResults written to {out_path}")


if __name__ == "__main__":
    main()
