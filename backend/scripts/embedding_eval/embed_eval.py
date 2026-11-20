"""Embed the targets and a query set with one model; report hit@k of the gold anchor.

Run from backend/ (needs env vars, so under Doppler):
  doppler run -- python -m scripts.embedding_eval.embed_eval biolord --tag author
  doppler run -- python -m scripts.embedding_eval.embed_eval bge_small \\
      --queries data/generated_pass1_labeled.json data/generated_pass2_labeled.json --valid-only --tag generated
`lexical` instead of a model gives the substring baseline (what the graph providers do today).
Writes results/<tag>_<model>.json (git-ignored). Torch/transformers/numpy arrive through deepeval.
"""
import argparse
import json
import time
from pathlib import Path

import numpy as np

from scripts.embedding_eval.scoring import anchor_scores, rank_of, summarise

HERE = Path(__file__).resolve().parent
CACHE, DATA, RESULTS = HERE / "cache", HERE / "data", HERE / "results"
BGE_INSTRUCTION = "Represent this sentence for searching relevant passages: "
MODELS: dict[str, dict] = {
    "bge_small": dict(repo="BAAI/bge-small-en-v1.5", pool="cls", max_len=64, prefixes={"noinstr": "", "instr": BGE_INSTRUCTION}),
    "biolord": dict(repo="FremyCompany/BioLORD-2023", pool="mean", max_len=64, prefixes={"none": ""}),
    "sapbert": dict(repo="cambridgeltl/SapBERT-from-PubMedBERT-fulltext", pool="cls", max_len=32, prefixes={"none": ""}),
    "spubmedbert": dict(repo="pritamdeka/S-PubMedBert-MS-MARCO", pool="mean", max_len=64, prefixes={"none": ""}),
}
TARGET_SETS: dict[str, set[str]] = {
    "anchor_only": {"snomed_anchor"},
    "anchor+ctas+v1": {"snomed_anchor", "ctas_name", "v1_alias"},
    "snomed_d1": {"snomed_anchor", "snomed_d1"},
    "snomed_d2": {"snomed_anchor", "snomed_d1", "snomed_d2"},
    "all_sources": {"snomed_anchor", "snomed_d1", "snomed_d2", "ctas_name", "v1_alias"},
}
AGGREGATIONS = ("max", "top3mean")


def load_queries(paths: list[Path], valid_only: bool) -> list[dict]:
    queries = [q for p in paths for q in json.loads(p.read_text())]
    return [q for q in queries if q.get("agree_top3", True)] if valid_only else queries


def encode(tokenizer, model, texts: list[str], pool: str, max_len: int, batch: int = 64) -> np.ndarray:
    import torch

    out = []
    for i in range(0, len(texts), batch):
        enc = tokenizer(texts[i:i + batch], padding=True, truncation=True, max_length=max_len, return_tensors="pt")
        with torch.no_grad():
            hidden = model(**enc).last_hidden_state
        if pool == "cls":
            vec = hidden[:, 0]
        else:
            mask = enc["attention_mask"].unsqueeze(-1).float()
            vec = (hidden * mask).sum(1) / mask.sum(1).clamp(min=1e-9)
        out.append(torch.nn.functional.normalize(vec, dim=-1).numpy())
    return np.concatenate(out)


def single_message_ms(tokenizer, model, cfg: dict, message: str, runs: int = 12) -> float:
    times = []
    for _ in range(runs):
        start = time.perf_counter()
        encode(tokenizer, model, [message], cfg["pool"], cfg["max_len"])
        times.append((time.perf_counter() - start) * 1000)
    return round(float(np.median(times[2:])), 1)


def evaluate(key: str, queries: list[dict], targets: list[dict], latency: bool) -> dict:
    anchors = sorted({t["anchor"] for t in targets})
    anchor_idx = {a: i for i, a in enumerate(anchors)}
    target_anchor = np.array([anchor_idx[t["anchor"]] for t in targets])
    target_source = np.array([t["source"] for t in targets])
    alias_texts = [t["text"] for t in targets if t["source"] in ("v1_alias", "ctas_name")]
    neutral = [not any(a in q["message"].lower() for a in alias_texts) for q in queries]
    gold = [anchor_idx[q["expected_complaint"]] for q in queries]
    result: dict = {"model": key, "n_queries": len(queries), "n_neutral": sum(neutral), "runs": []}

    if key == "lexical":
        for name, sources in TARGET_SETS.items():
            subset = [t for t in targets if t["source"] in sources]
            ranks = [1 if any(t["anchor"] == q["expected_complaint"] and t["text"] in q["message"].lower() for t in subset) else 999
                     for q in queries]
            result["runs"].append({"prefix": "-", "agg": "substring", "targets": name, **summarise(ranks, neutral)})
        return result

    from transformers import AutoModel, AutoTokenizer

    cfg = MODELS[key]
    tokenizer, model = AutoTokenizer.from_pretrained(cfg["repo"]), AutoModel.from_pretrained(cfg["repo"]).eval()
    cache = CACHE / f"emb_{key}.npy"
    if cache.exists():
        embeddings = np.load(cache)
    else:
        embeddings = encode(tokenizer, model, [t["text"] for t in targets], cfg["pool"], cfg["max_len"])
        np.save(cache, embeddings)
    if latency:
        result["single_msg_ms_torch_fp32"] = single_message_ms(tokenizer, model, cfg, queries[0]["message"])
    for prefix_name, prefix in cfg["prefixes"].items():
        q_emb = encode(tokenizer, model, [prefix + q["message"] for q in queries], cfg["pool"], cfg["max_len"])
        for name, sources in TARGET_SETS.items():
            keep = np.isin(target_source, list(sources))
            sims = q_emb @ embeddings[keep].T
            for agg in AGGREGATIONS:
                ranks = [rank_of(anchor_scores(sims[i], target_anchor[keep], len(anchors), agg), gold[i]) for i in range(len(queries))]
                result["runs"].append({"prefix": prefix_name, "agg": agg, "targets": name, **summarise(ranks, neutral)})
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("model", choices=[*MODELS, "lexical"])
    parser.add_argument("--queries", nargs="+", type=Path, default=[DATA / "author_lay_queries.json"])
    parser.add_argument("--valid-only", action="store_true", help="keep only messages whose gold anchor is in the labeler's top 3")
    parser.add_argument("--tag", default="run")
    parser.add_argument("--latency", action="store_true", help="also time one message (torch fp32, this machine)")
    args = parser.parse_args()
    targets = [json.loads(line) for line in (CACHE / "targets.jsonl").read_text().splitlines()]
    queries = load_queries(args.queries, args.valid_only)
    result = evaluate(args.model, queries, targets, args.latency)
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / f"{args.tag}_{args.model}.json").write_text(json.dumps(result, indent=1))
    print(args.model, "ok:", result["n_queries"], "queries,", result["n_neutral"], "neutral")


if __name__ == "__main__":
    main()
