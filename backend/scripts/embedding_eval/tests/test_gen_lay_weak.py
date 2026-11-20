import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
os.environ.setdefault("OPENAI_API_KEY", "test-key-not-used")  # the module builds a client at import; no call is made

from scripts.embedding_eval.gen_lay_descriptions import anchors_without_confirmed, merge_candidates


def _row(idx: int, phrase: str, agree: bool) -> dict:
    return {"idx": idx, "phrase": phrase, "agree_top3": agree}


def test_anchors_without_confirmed_lists_only_anchors_below_minimum():
    rows = [_row(1, "a b", True), _row(1, "c d", False), _row(2, "e f", False), _row(3, "g h", True), _row(3, "i j", True)]
    assert anchors_without_confirmed(rows) == [2]
    assert anchors_without_confirmed(rows, minimum=2) == [1, 2]


def test_weak_mode_keeps_existing_confirmed_phrases():
    existing = [_row(2, "old one", False), _row(1, "keep me", True)]
    regenerated = [_row(2, "new one", True), _row(2, "old one", True)]
    merged = merge_candidates(existing, regenerated)
    assert _row(1, "keep me", True) in merged
    assert [r["phrase"] for r in merged if r["idx"] == 2] == ["old one", "new one"]  # no duplicate, existing row not overwritten
