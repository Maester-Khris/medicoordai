"""The demo loader gives emergent only to hospitals on the ER list."""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../scripts/demo_seed"))

from seed_facilities import (  # noqa: E402
    ALL_SEVERITIES,
    NON_EMERGENT,
    accepted_severity_for,
    load_emergency_department_ids,
    prepare,
)

ER = "11111111-1111-1111-1111-111111111111"
REHAB = "22222222-2222-2222-2222-222222222222"
CLINIC = "33333333-3333-3333-3333-333333333333"
GONE = "44444444-4444-4444-4444-444444444444"


def _row(fid: str, name: str, category: str, severity: list[str], lat: float) -> dict:
    return {"facility_id": fid, "facility_name": name, "category": category, "source_facility_type": "general",
            "accepted_severity": severity, "address": "1 King St W", "lat": lat, "lng": -79.38,
            "business_status": "OPERATIONAL", "is_operational": True}


def test_a_listed_hospital_accepts_emergent() -> None:
    assert accepted_severity_for(_row(ER, "General", "hospital", NON_EMERGENT, 43.6), frozenset({ER})) == ALL_SEVERITIES


def test_an_unlisted_hospital_loses_emergent_even_if_the_source_gives_it() -> None:
    row = _row(REHAB, "Rehab Centre", "hospital", ALL_SEVERITIES, 43.6)
    assert accepted_severity_for(row, frozenset({ER})) == NON_EMERGENT


def test_other_categories_keep_their_source_severities() -> None:
    row = _row(CLINIC, "Clinic", "ambulatory", ["urgent", "moderate", "routine"], 43.6)
    assert accepted_severity_for(row, frozenset({CLINIC})) == ["urgent", "moderate", "routine"]


def test_prepare_applies_the_rule_and_warns_about_listed_ids_that_are_not_hospitals() -> None:
    clean = [_row(ER, "General", "hospital", ALL_SEVERITIES, 43.61),
             _row(REHAB, "Rehab Centre", "hospital", ALL_SEVERITIES, 43.62),
             _row(CLINIC, "Clinic", "ambulatory", ["urgent", "moderate", "routine"], 43.63)]
    ready, rejected, warnings = prepare(clean, [], frozenset({ER, CLINIC, GONE}))

    severity = {r["id"]: r["accepted_severity"] for r in ready}
    assert severity == {ER: ALL_SEVERITIES, REHAB: NON_EMERGENT, CLINIC: ["urgent", "moderate", "routine"]}
    assert rejected == []
    assert any("2 listed ER id(s) are not hospitals in this load" in w for w in warnings)


@pytest.mark.parametrize("content", [{"facilities": []}, {"_about": "no list"}])
def test_a_missing_or_empty_list_stops_the_load(tmp_path, content: dict) -> None:
    path = tmp_path / "emergency_departments.json"
    path.write_text(json.dumps(content))
    with pytest.raises(SystemExit):
        load_emergency_department_ids(path)
