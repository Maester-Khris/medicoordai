import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from services import facility_bytes


@pytest.fixture(autouse=True)
def _clean():
    facility_bytes.clear()
    yield
    facility_bytes.clear()


def test_the_etag_is_quoted_and_depends_on_every_part_of_the_key() -> None:
    base = facility_bytes.etag_for(("f1", "w1", None, None, None))
    assert base.startswith('"') and base.endswith('"') and len(base) == 34
    assert facility_bytes.etag_for(("f1", "w1", None, None, None)) == base
    for other in (("f2", "w1", None, None, None), ("f1", "w2", None, None, None),
                  ("f1", "w1", "hospital", None, None), ("f1", "w1", None, "urgent", None),
                  ("f1", "w1", None, None, 30)):
        assert facility_bytes.etag_for(other) != base


def test_encode_is_compact_utf8_json() -> None:
    body = facility_bytes.encode([{"id": "a", "raw_wait": "45m–2h"}])
    assert body == '[{"id":"a","raw_wait":"45m–2h"}]'.encode("utf-8")
    assert json.loads(body) == [{"id": "a", "raw_wait": "45m–2h"}]


def test_a_stored_body_is_returned_and_an_unknown_key_is_none() -> None:
    facility_bytes.put(("k",), b"[]")
    assert facility_bytes.get(("k",)) == b"[]"
    assert facility_bytes.get(("other",)) is None


def test_the_least_recently_used_entry_is_dropped_past_the_limit() -> None:
    for i in range(facility_bytes.MAX_ENTRIES):
        facility_bytes.put((i,), b"x")
    assert facility_bytes.get((0,)) == b"x"  # touch the oldest: it becomes the newest
    facility_bytes.put(("new",), b"y")
    assert facility_bytes.get((0,)) == b"x"
    assert facility_bytes.get((1,)) is None
    assert facility_bytes.get(("new",)) == b"y"
