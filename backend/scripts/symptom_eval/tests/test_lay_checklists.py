import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from scripts.symptom_eval.vignette_loader import CHECKLISTS_DIR, CHECKLISTS_LAY_DIR


def _json_files(directory: str) -> list[str]:
    return sorted(name for name in os.listdir(directory) if name.endswith(".json"))


def _load(directory: str, name: str) -> dict:
    with open(os.path.join(directory, name)) as f:
        return json.load(f)


def _feature_shape(checklist: dict) -> list[tuple]:
    return [
        (item["feature_id"], item["category"], item["reveal_only_if_asked"])
        for item in checklist["disclosure_items"]
    ]


def test_lay_checklists_match_originals():
    for name in _json_files(CHECKLISTS_LAY_DIR):
        assert name in _json_files(CHECKLISTS_DIR), f"{name} has no original checklist"
        original, lay = _load(CHECKLISTS_DIR, name), _load(CHECKLISTS_LAY_DIR, name)

        assert set(lay) - {"excluded_from_pairing"} == set(original), name
        assert _feature_shape(lay) == _feature_shape(original), name
