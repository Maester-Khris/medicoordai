"""Build the target strings per anchor: SNOMED CA-Edition descriptions of each anchor and its
descendants (depth <= 2), plus the CTAS complaint name and the v1 aliases. Writes cache/targets.jsonl.

Run from backend/:  python -m scripts.embedding_eval.build_targets
"""
import collections
import json
import os
import re
from pathlib import Path

from graph.snomed_neo4j.anchor_mapping import ANCHOR_MAPPINGS

HERE = Path(__file__).resolve().parent
CACHE = HERE / "cache"
TRIAGE_DATA = HERE.parent.parent / "triage" / "resources" / "symptom_triage_data.json"
SNOMED_DIR = Path(os.environ.get(
    "SNOMED_CA_TERMINOLOGY_DIR",
    "/databank/snomed_ct_ca/SnomedCT_Canadian_EditionRelease_PRODUCTION_20260531T120000Z/Snapshot/Terminology",
))
RELATIONSHIPS = SNOMED_DIR / "sct2_Relationship_Snapshot_CanadianEdition_20260531.txt"
DESCRIPTIONS = SNOMED_DIR / "sct2_Description_Snapshot_CanadianEdition_20260531.txt"
IS_A, INFERRED = "116680003", "900000000000011006"
FSN, SYNONYM = "900000000000003001", "900000000000013009"
MAX_DEPTH = 2


def load_children() -> dict[str, list[str]]:
    children: dict[str, list[str]] = collections.defaultdict(list)
    with open(RELATIONSHIPS, encoding="utf-8") as f:
        next(f)
        for line in f:
            p = line.rstrip("\n").split("\t")
            if p[2] == "1" and p[7] == IS_A and p[8] == INFERRED:
                children[p[5]].append(p[4])
    return children


def depths_by_anchor(anchors: dict[str, str], children: dict[str, list[str]]) -> dict[tuple[str, str], int]:
    depth_of: dict[tuple[str, str], int] = {}
    for anchor in anchors:
        depth_of[(anchor, anchor)] = 0
        frontier, seen = [anchor], {anchor}
        for depth in range(1, MAX_DEPTH + 1):
            nxt = []
            for concept in frontier:
                for child in children.get(concept, []):
                    if child not in seen:
                        seen.add(child)
                        nxt.append(child)
                        depth_of[(anchor, child)] = depth
            frontier = nxt
    return depth_of


def load_terms(needed: set[str]) -> dict[str, set[str]]:
    terms: dict[str, set[str]] = collections.defaultdict(set)
    with open(DESCRIPTIONS, encoding="utf-8") as f:
        next(f)
        for line in f:
            p = line.rstrip("\n").split("\t")
            if p[2] == "1" and p[5] == "en" and p[4] in needed and p[6] in (FSN, SYNONYM):
                term = re.sub(r"\s*\([^()]*\)$", "", p[7]).strip() if p[6] == FSN else p[7].strip()
                if term:
                    terms[p[4]].add(term.lower())
    return terms


def build() -> list[dict]:
    anchors = {m.anchor_concept_id: m.ctas_alias for m in ANCHOR_MAPPINGS}
    depth_of = depths_by_anchor(anchors, load_children())
    terms = load_terms({concept for (_, concept) in depth_of})
    v1 = {e["name"]: e for e in json.loads(TRIAGE_DATA.read_text())}
    rows: dict[tuple[str, str, str], dict] = {}

    def add(anchor: str, text: str, source: str) -> None:
        if text:
            rows.setdefault((anchor, text, source), {"anchor": anchor, "text": text, "source": source})

    for (anchor_id, concept), depth in depth_of.items():
        source = "snomed_anchor" if depth == 0 else f"snomed_d{depth}"
        for text in terms.get(concept, ()):
            add(anchors[anchor_id], text, source)
    for name in anchors.values():
        add(name, name.lower(), "ctas_name")
        for alias in v1.get(name, {}).get("aliases", []):
            add(name, alias.lower(), "v1_alias")
    return list(rows.values())


def main() -> None:
    rows = build()
    CACHE.mkdir(exist_ok=True)
    with open(CACHE / "targets.jsonl", "w") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")
    print(len(rows), "targets:", dict(collections.Counter(r["source"] for r in rows)))


if __name__ == "__main__":
    main()
