import json

import pytest

from scripts.snomed_ingest.import_lay_candidates import convert_candidates
from scripts.snomed_ingest.lay_descriptions import (
    LayPhrase,
    lay_description_id,
    load_lay_descriptions,
    select_for_index,
)


def _write(tmp_path, phrases):
    path = tmp_path / "lay.json"
    path.write_text(json.dumps({"version": 1, "phrases": phrases}))
    return path


def _p(anchor="1", text="my nose is blocked", status="generated", source="m"):
    return {"anchor_id": anchor, "text": text, "source": source, "status": status}


def test_loader_rejects_unknown_status_and_unknown_anchor(tmp_path):
    with pytest.raises(ValueError):
        load_lay_descriptions(_write(tmp_path, [_p(status="bogus")]), {"1"})
    with pytest.raises(ValueError):
        load_lay_descriptions(_write(tmp_path, [_p(anchor="9")]), {"1"})


def test_phrases_under_two_words_are_dropped_and_duplicates_collapsed(tmp_path):
    path = _write(tmp_path, [_p(text="cough"), _p(text="a dry cough"), _p(text="a dry cough")])
    loaded = load_lay_descriptions(path, {"1"})
    assert [p.text for p in loaded] == ["a dry cough"]


def _phrases():
    return [LayPhrase("1", f"phrase {s}", "m", s) for s in ("generated", "confirmed", "rejected", "approved")]


def test_rule_all_excludes_rejected():
    assert {p.status for p in select_for_index(_phrases(), "all")} == {"generated", "confirmed", "approved"}


def test_rule_confirmed_includes_approved():
    assert {p.status for p in select_for_index(_phrases(), "confirmed")} == {"confirmed", "approved"}


def test_rule_approved_is_strictest():
    assert {p.status for p in select_for_index(_phrases(), "approved")} == {"approved"}
    with pytest.raises(ValueError):
        select_for_index(_phrases(), "nonsense")


def test_description_id_is_stable_and_prefixed():
    a = lay_description_id("68235000", "my nose is blocked")
    assert a == lay_description_id("68235000", "my nose is blocked")
    assert a.startswith("lay:68235000:") and len(a.split(":")[2]) == 12
    assert a != lay_description_id("68235000", "other words here")


def test_convert_candidates_maps_agreement_to_status():
    rows = [
        {"anchor_concept_id": "1", "phrase": "my nose is blocked", "source": "gpt-4o-mini", "agree_top3": True},
        {"anchor_concept_id": "1", "phrase": "stuffy and drippy", "source": "gpt-4o-mini", "agree_top3": False},
    ]
    out = convert_candidates(rows)
    assert out["version"] == 1
    assert [(p["status"], p["source"]) for p in out["phrases"]] == [
        ("confirmed", "gpt-4o-mini"),
        ("generated", "gpt-4o-mini"),
    ]
    assert out["phrases"][0]["anchor_id"] == "1" and out["phrases"][0]["text"] == "my nose is blocked"
