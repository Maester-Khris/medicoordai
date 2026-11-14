"""Evaluate the SHIPPED index and embedder against the retrieval screen.

What is measured is what ships: the production OnnxEmbedder, the real SemanticIndex built from the graph, and the
production abstention rule. Run from backend/ (needs the env vars for nothing but imports, so under Doppler):

  python -m scripts.embedding_eval.eval_index --model-dir results/onnx/biolord --index-dir results/index/biolord

Thresholds are calibrated on one in-scope query set plus the validation half of the negative set, then every query set is
scored against the test half of the negatives, so the false-match number is never measured on the data it was tuned on.
"""
import argparse
import json
import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

from graph.semantic.abstention import decide
from graph.semantic.build import load_model_card
from graph.semantic.embedder import Embedder, OnnxEmbedder
from graph.semantic.index import SemanticIndex, read_manifest
from graph.semantic.settings import SemanticSettings
from scripts.embedding_eval.calibrate import Thresholds, calibrate_thresholds, load_negative_set, split_negative_set

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
TOP_K = 5
MIN_HIT5_LOWER_BOUND = 0.75  # starting budget, approved and unsourced (plan: Global Constraints)
MAX_FALSE_MATCH = 0.05
DEFAULT_QUERY_SETS = {
    "author": DATA / "author_lay_queries.json",
    "gen1": DATA / "generated_pass1_labeled.json",
    "gen2": DATA / "generated_pass2_labeled.json",
    "third": DATA / "generated_third_labeled.json",
}


@dataclass(frozen=True)
class ScreenReport:
    hit1: float
    hit5: float
    hit5_ci95: tuple[float, float]
    false_match: float
    in_scope_retained: float
    p50_ms: float
    p95_ms: float


def wilson_ci(hits: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson score interval for a rate, as fractions (the normal approximation is poor at small n or near 0/1)."""
    if n == 0:
        return (0.0, 1.0)
    p = hits / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, float(centre - half)), min(1.0, float(centre + half)))


def passes_screen(r: ScreenReport) -> bool:
    return r.hit5_ci95[0] >= MIN_HIT5_LOWER_BOUND and r.false_match <= MAX_FALSE_MATCH


def load_queries(paths: Sequence[Path], valid_only: bool) -> list[dict]:
    """Query files carry `idx` (position in ANCHOR_MAPPINGS); add the anchor id the index uses."""
    from graph.snomed_neo4j.anchor_mapping import ANCHOR_MAPPINGS

    items: list[dict] = []
    for path in paths:
        for item in json.loads(Path(path).read_text()):
            if valid_only and item.get("agree_top3") is False:
                continue
            items.append({**item, "anchor_id": ANCHOR_MAPPINGS[item["idx"]].anchor_concept_id})
    return items


def score_message(index: SemanticIndex, embedder: Embedder, text: str) -> tuple[list[tuple[str, float]], float] | None:
    """Anchors ranked by best row score, plus the embed+search time in ms. None when the production source would skip the
    message (no letter or digit): such a message can never be accepted, so it is not embedded."""
    if not any(ch.isalnum() for ch in text):
        return None
    started = time.perf_counter()
    vector = embedder.embed(text)
    hits = index.search(vector, len(index.rows))
    elapsed_ms = (time.perf_counter() - started) * 1000
    best: dict[str, float] = {}
    for hit in hits:
        anchor = hit.row.anchor_id
        best[anchor] = max(hit.score, best.get(anchor, hit.score))
    return sorted(best.items(), key=lambda kv: kv[1], reverse=True), elapsed_ms


def _accepted(ranked: list[tuple[str, float]], thresholds: Thresholds) -> bool:
    return decide(dict(ranked), thresholds.threshold, thresholds.margin).accepted


def evaluate(index: SemanticIndex, embedder: Embedder, queries: Sequence[dict], negatives: Sequence[dict],
             thresholds: Thresholds) -> ScreenReport:
    timings: list[float] = []
    hit1 = hit5 = retained = 0
    for query in queries:
        scored = score_message(index, embedder, query["message"])
        if scored is None:
            continue
        ranked, ms = scored
        timings.append(ms)
        order = [anchor for anchor, _ in ranked]
        hit1 += order[:1] == [query["anchor_id"]]
        hit5 += query["anchor_id"] in order[:TOP_K]
        retained += _accepted(ranked, thresholds)
    false_matches = 0
    for negative in negatives:
        scored = score_message(index, embedder, negative["text"])
        if scored is None:
            continue
        ranked, ms = scored
        timings.append(ms)
        false_matches += _accepted(ranked, thresholds)
    n = len(queries)
    return ScreenReport(
        hit1=hit1 / n if n else 0.0, hit5=hit5 / n if n else 0.0, hit5_ci95=wilson_ci(hit5, n),
        false_match=false_matches / len(negatives) if negatives else 0.0, in_scope_retained=retained / n if n else 0.0,
        p50_ms=float(np.percentile(timings, 50)) if timings else 0.0, p95_ms=float(np.percentile(timings, 95)) if timings else 0.0)


def score_pairs(index: SemanticIndex, embedder: Embedder, texts: Sequence[str]) -> list[tuple[float, float]]:
    """(top anchor score, gap to the second anchor) per embeddable text: the inputs of threshold calibration."""
    pairs: list[tuple[float, float]] = []
    for text in texts:
        scored = score_message(index, embedder, text)
        if scored is None:
            continue
        ranked = scored[0]
        top = ranked[0][1]
        pairs.append((top, top - ranked[1][1] if len(ranked) > 1 else top))
    return pairs


def _parse_sets(specs: Sequence[str] | None) -> dict[str, Path]:
    if not specs:
        return {name: path for name, path in DEFAULT_QUERY_SETS.items() if path.exists()}
    return {name: Path(path) for name, path in (spec.split("=", 1) for spec in specs)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--index-dir", type=Path, required=True)
    parser.add_argument("--queries", nargs="*", help="NAME=PATH pairs (default: the author, generated and third sets present)")
    parser.add_argument("--threads", type=int, default=1)
    parser.add_argument("--seed", type=int, default=13)
    parser.add_argument("--calibrate-on", default=None, help="query set used for the in-scope side of calibration (default: first)")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    card = load_model_card(args.model_dir)
    settings = SemanticSettings(model_dir=args.model_dir, index_dir=args.index_dir, score_threshold=0.5, gap_margin=0.02,
                                lay_rule="confirmed", threads=args.threads)
    embedder = OnnxEmbedder(args.model_dir, settings, card.pooling, card.prefix, card.max_len)
    embedder.warm_up()
    index = SemanticIndex.load(args.index_dir, read_manifest(args.index_dir))

    sets = _parse_sets(args.queries)
    queries = {name: load_queries([path], valid_only=True) for name, path in sets.items()}
    validation, test = split_negative_set(load_negative_set(DATA / "negative_queries.json"), args.seed)
    calibrate_name = args.calibrate_on or next(iter(queries))
    in_scope_pairs = score_pairs(index, embedder, [q["message"] for q in queries[calibrate_name]])
    negative_pairs = score_pairs(index, embedder, [n["text"] for n in validation])
    thresholds = calibrate_thresholds(in_scope_pairs, negative_pairs, target_false_match=MAX_FALSE_MATCH)
    print(f"model {card.model_id}  calibrated on {calibrate_name} + {len(validation)} validation negatives: "
          f"threshold {thresholds.threshold:.3f} margin {thresholds.margin:.3f} "
          f"(calibration false-match {thresholds.false_match:.3f}, retained {thresholds.in_scope_retained:.3f})")
    results: dict[str, dict] = {"model": card.model_id, "thresholds": asdict(thresholds)}
    for name, items in queries.items():
        report = evaluate(index, embedder, items, test, thresholds)
        verdict = "PASS" if passes_screen(report) else "FAIL"
        print(f"{name:7s} n={len(items):4d} hit1 {report.hit1:.3f} hit5 {report.hit5:.3f} "
              f"[{report.hit5_ci95[0]:.3f}-{report.hit5_ci95[1]:.3f}] retained {report.in_scope_retained:.3f} "
              f"false-match(test) {report.false_match:.3f} p50 {report.p50_ms:.1f} ms p95 {report.p95_ms:.1f} ms  {verdict}")
        results[name] = {"n": len(items), **asdict(report), "passes": verdict == "PASS"}
    if args.out:
        args.out.write_text(json.dumps(results, indent=1))


if __name__ == "__main__":
    main()
