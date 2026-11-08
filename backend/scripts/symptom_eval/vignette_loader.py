"""
Loads the raw Ontario CTAS vignette pool and merges each entry with its
authored disclosure checklist (backend/scripts/symptom_eval/checklists/),
producing Vignette domain objects. The raw JSON has no first-person text
and no per-feature checklist — checklists/<case_id>.json (authored via
checklist_extractor.py, Task 3) is where that gap gets closed.

A vignette with no checklist file yet is skipped, not an error — this lets
the harness run against a partially-authored pool during rollout instead of
failing until all 27 are done.
"""
import json
import os

from scripts.reconcile_ctas_data import CTAS_TO_APP_SEVERITY
from scripts.symptom_eval.domain import DisclosureItem, Vignette

RAW_VIGNETTES_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "triage", "resources",
    "eval_vignettes_ontario_ctas.json",
)
CHECKLISTS_DIR = os.path.join(os.path.dirname(__file__), "checklists")
CHECKLISTS_LAY_DIR = os.path.join(os.path.dirname(__file__), "checklists_lay")
VARIANTS = ("original", "lay")


def checklists_dir_for(variant: str) -> str:
    if variant == "original":
        return CHECKLISTS_DIR
    if variant == "lay":
        return CHECKLISTS_LAY_DIR
    raise ValueError(f"unknown variant {variant!r}; expected one of {VARIANTS}")


def load_raw_vignettes(path: str = RAW_VIGNETTES_PATH) -> list[dict]:
    with open(path) as f:
        return json.load(f)


def load_checklist(case_id: str, checklists_dir: str = CHECKLISTS_DIR) -> dict | None:
    path = os.path.join(checklists_dir, f"{case_id}.json")
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


def build_vignette(raw: dict, checklist: dict) -> Vignette:
    arrival = raw["questions"][0]
    departure = (
        raw["questions"][1]
        if len(raw["questions"]) > 1 and "Departure" in raw["questions"][1]["prompt"]
        or (len(raw["questions"]) > 1 and "departure" in raw["questions"][1]["prompt"].lower())
        else None
    )

    return Vignette(
        case_id=str(raw["case_id"]),
        opening_message=checklist["opening_message"],
        disclosure_items=[
            DisclosureItem(**item) for item in checklist["disclosure_items"]
        ],
        gold_severity=CTAS_TO_APP_SEVERITY[arrival["ctas_level"]],
        gold_ctas_level=arrival["ctas_level"],
        update_message=checklist.get("update_message"),
        updated_gold_severity=(
            CTAS_TO_APP_SEVERITY[departure["ctas_level"]] if departure else None
        ),
        source_pages=raw.get("source_pages", ""),
        pairing_exclusion=checklist.get("excluded_from_pairing"),
    )


def load_all_vignettes(
    raw_path: str = RAW_VIGNETTES_PATH,
    checklists_dir: str | None = None,
    variant: str = "original",
) -> list[Vignette]:
    checklists_dir = checklists_dir or checklists_dir_for(variant)
    vignettes = []
    for raw in load_raw_vignettes(raw_path):
        checklist = load_checklist(str(raw["case_id"]), checklists_dir)
        if checklist is None:
            continue
        vignettes.append(build_vignette(raw, checklist))
    return vignettes
