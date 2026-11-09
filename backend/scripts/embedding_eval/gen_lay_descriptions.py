"""Generate candidate lay-language descriptions (short everyday phrases) for each CTAS/SNOMED anchor, then run a
blind label check on every phrase. Costs money (about $0.05 on gpt-4o-mini): run it deliberately, under Doppler
with OPENAI_API_KEY set. Writes results/lay_description_candidates.json (git-ignored). Nothing is added to the graph.

  python -m scripts.embedding_eval.gen_lay_descriptions

Per anchor: ten phrases of 2 to 8 words, given the complaint name, its SNOMED term and the wordings the graph already has
(so new phrases add coverage). Each phrase is then assigned to categories by a blind labeler; `agree_top3` records whether
the anchor is in the labeler's top 3. Phrases that fail stay in the file marked as such: review decides, not this script.
"""
import collections
import json
import random
import sys
from concurrent.futures import ThreadPoolExecutor

from graph.snomed_neo4j.anchor_mapping import ANCHOR_MAPPINGS
from scripts.embedding_eval import gen_queries as g

PHRASES_PER_ANCHOR = 10
MIN_WORDS, MAX_WORDS = 2, 8
LABEL_BATCH = 30
PHRASES_FILE = g.RESULTS / "lay_description_phrases.json"  # generation is cached so labeling can be rerun without paying again
V1_DATA = g.HERE.parent.parent / "triage" / "resources" / "symptom_triage_data.json"


def known_wordings() -> dict[str, list[str]]:
    return {entry["name"]: entry.get("aliases", []) for entry in json.loads(V1_DATA.read_text())}


def clean_phrases(raw: list[str], known: set[str]) -> list[str]:
    seen, kept = set(known), []
    for phrase in raw:
        text = " ".join(str(phrase).strip().strip(".").lower().split())
        if MIN_WORDS <= len(text.split()) <= MAX_WORDS and text not in seen:
            seen.add(text)
            kept.append(text)
    return kept


def anchors_without_confirmed(candidates: list[dict], minimum: int = 1) -> list[int]:
    """Anchor indexes that have fewer than `minimum` labeler-confirmed phrases (sorted)."""
    confirmed = collections.Counter({r["idx"]: 0 for r in candidates})
    confirmed.update(r["idx"] for r in candidates if r["agree_top3"])
    return sorted(i for i, n in confirmed.items() if n < minimum)


def merge_candidates(existing: list[dict], regenerated: list[dict]) -> list[dict]:
    """Existing rows always survive untouched; regenerated rows are appended unless (idx, phrase) is already there."""
    seen = {(r["idx"], r["phrase"]) for r in existing}
    return existing + [r for r in regenerated if (r["idx"], r["phrase"]) not in seen]


def phrases_for(idx: int, fsn: str, aliases: list[str], detailed: bool = False) -> list[str]:
    cues = ("Each phrase should carry a defining fact (the cause or how it happened, the body part, who it affects, when) "
            "so it cannot be confused with similar problems. ") if detailed else ""
    reply = g.json_chat(
        "You write everyday-language wordings for medical complaint categories, for a triage evaluation dataset.",
        f"Complaint category: {g.name_of(idx)}\nClinical term: {fsn}\nWordings we already have (do not repeat): {aliases or 'none'}\n\n"
        f"Write {PHRASES_PER_ANCHOR} different short phrases ({MIN_WORDS} to {MAX_WORDS} words each) that a layperson, parent or bystander might use "
        "to refer to this problem or its main symptom. Mix sensation words, what it looks like, how a child would say it, and informal wording. "
        f"No medical jargon, no diagnosis names, no brand names. {cues}" 'Return JSON: {"phrases": ["...", "..."]}',
        temperature=0.8, max_tokens=400)
    return clean_phrases(reply["phrases"], {a.lower() for a in aliases})


def generate_all(mappings: dict) -> dict[int, list[str]]:
    wordings = known_wordings()
    with ThreadPoolExecutor(8) as pool:
        phrases = pool.map(lambda i: phrases_for(i, mappings[i].fsn, wordings.get(mappings[i].ctas_alias, [])), mappings)
        return dict(zip(mappings, phrases))


def label_rows(items: list[tuple[int, str]], mappings: dict) -> list[dict]:
    random.Random(13).shuffle(items)  # consecutive similar phrases get labeled as a block otherwise
    catalog = "\n".join(f"{i}: {g.name_of(i)}" for i in range(len(g.NAMES)) if i not in g.SKIP)
    with ThreadPoolExecutor(6) as pool:
        batches = pool.map(lambda s: g.label_batch(items[s:s + LABEL_BATCH], catalog), range(0, len(items), LABEL_BATCH))
        labeled = [row for batch in batches for row in batch]
    return [{"idx": r["idx"], "anchor_concept_id": mappings[r["idx"]].anchor_concept_id, "anchor": r["expected_complaint"],
             "phrase": r["message"], "source": g.MODEL, "labeler_top3": r["labeler_top3"],
             "agree_top1": r["agree_top1"], "agree_top3": r["agree_top3"]} for r in labeled]


def run_weak(mappings: dict) -> None:
    """Regenerate (cue-preserving prompt) only for anchors with no confirmed phrase; existing rows are kept."""
    path = g.RESULTS / "lay_description_candidates.json"
    existing = json.loads(path.read_text())
    weak = anchors_without_confirmed(existing)
    wordings = known_wordings()
    known = {r["phrase"] for r in existing}
    items = [(i, p) for i in weak for p in phrases_for(i, mappings[i].fsn, wordings.get(mappings[i].ctas_alias, []), detailed=True)
             if p not in known]
    merged = merge_candidates(existing, label_rows(items, mappings))
    path.write_text(json.dumps(merged, indent=1))
    left = anchors_without_confirmed(merged)
    print(f"weak anchors {len(weak)} -> {len(left)} still without a confirmed phrase; +{len(merged) - len(existing)} rows; est ${g.cost_usd():.4f}")


def main() -> None:
    g.HARD_STOP_USD = 0.12
    mappings = {i: m for i, m in enumerate(ANCHOR_MAPPINGS) if i not in g.SKIP}
    g.RESULTS.mkdir(exist_ok=True)
    if "--weak" in sys.argv:
        return run_weak(mappings)
    if PHRASES_FILE.exists():
        generated = {int(k): v for k, v in json.loads(PHRASES_FILE.read_text()).items()}
    else:
        generated = generate_all(mappings)
        PHRASES_FILE.write_text(json.dumps(generated, indent=1))
    items = [(i, p) for i, phrases in generated.items() for p in phrases]
    # Shuffle before labeling: consecutive similar phrases get labeled as a block otherwise (seen on the first run).
    random.Random(13).shuffle(items)
    catalog = "\n".join(f"{i}: {g.name_of(i)}" for i in range(len(g.NAMES)) if i not in g.SKIP)
    with ThreadPoolExecutor(6) as pool:
        batches = pool.map(lambda s: g.label_batch(items[s:s + LABEL_BATCH], catalog), range(0, len(items), LABEL_BATCH))
        labeled = [row for batch in batches for row in batch]
    out = [{"idx": r["idx"], "anchor_concept_id": mappings[r["idx"]].anchor_concept_id, "anchor": r["expected_complaint"],
            "phrase": r["message"], "source": g.MODEL, "labeler_top3": r["labeler_top3"],
            "agree_top1": r["agree_top1"], "agree_top3": r["agree_top3"]} for r in labeled]
    path = g.RESULTS / "lay_description_candidates.json"
    path.write_text(json.dumps(out, indent=1))
    per_anchor = collections.Counter(r["idx"] for r in out)
    n = len(out)
    print(f"{n} phrases over {len(per_anchor)} anchors (min {min(per_anchor.values())}, max {max(per_anchor.values())} per anchor) -> {path}; "
          f"labeler top1 {sum(r['agree_top1'] for r in out) / n:.3f} top3 {sum(r['agree_top3'] for r in out) / n:.3f}; est ${g.cost_usd():.4f}")


if __name__ == "__main__":
    main()
