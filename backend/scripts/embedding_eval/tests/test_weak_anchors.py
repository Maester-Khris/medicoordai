import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))
os.environ.setdefault("OPENAI_API_KEY", "test-key-not-used")  # the module builds a client at import; no call is made

from scripts.embedding_eval.gen_queries import weak_anchors


def _item(idx: int, agree: bool) -> dict:
    return {"idx": idx, "agree_top3": agree}


def test_weak_anchors_are_those_confirmed_less_than_half_the_time():
    labeled = [_item(1, True), _item(1, True), _item(2, True), _item(2, False),
               _item(3, False), _item(3, False), _item(3, True)]
    assert weak_anchors(labeled) == [3]  # 1: 100%, 2: 50% (not weak), 3: 33%


def test_threshold_is_adjustable():
    assert weak_anchors([_item(2, True), _item(2, False)], threshold=0.75) == [2]
