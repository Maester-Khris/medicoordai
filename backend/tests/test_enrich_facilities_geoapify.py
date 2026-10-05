"""Unit tests for the pure functions of enrich_facilities_geoapify (no network, no database)."""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../scripts/demo_seed"))

from enrich_facilities_geoapify import (  # noqa: E402
    build_patch,
    haversine_m,
    is_hours_missing,
    name_overlap,
    needs_enrichment,
    pick_match,
)

# Toronto General Hospital
LAT, LNG = 43.6585958, -79.3881616


def _offset_north(metres: float) -> float:
    return LAT + metres / 111_320.0


# ── haversine_m ───────────────────────────────────────────────────────────────

def test_haversine_zero_for_same_point() -> None:
    assert haversine_m(LAT, LNG, LAT, LNG) == 0


def test_haversine_known_distance() -> None:
    assert 195 < haversine_m(LAT, LNG, _offset_north(200), LNG) < 205


# ── name_overlap ──────────────────────────────────────────────────────────────

def test_overlap_subset_name_passes() -> None:
    assert name_overlap("Toronto General Hospital", "University Health Network - Toronto General Hospital") == 1.0


def test_overlap_different_names_fail() -> None:
    assert name_overlap("Chartwell Avondale Retirement Residence", "Sunnybrook Health Sciences Centre") == 0.0


def test_overlap_stopwords_only_is_zero() -> None:
    assert name_overlap("The Hospital", "Health Centre") == 0.0


def test_overlap_empty_is_zero() -> None:
    assert name_overlap("", "Toronto Western") == 0.0
    assert name_overlap(None, "Toronto Western") == 0.0  # type: ignore[arg-type]


def test_overlap_ignores_apostrophes_and_case() -> None:
    assert name_overlap("St. Michael's Hospital", "ST MICHAELS") == 1.0


# ── pick_match ────────────────────────────────────────────────────────────────

FACILITY = {"id": "f1", "name": "Toronto General Hospital", "lat": LAT, "lng": LNG}


def _cand(name: str, metres: float, place_id: str = "pid") -> dict:
    return {"name": name, "lat": _offset_north(metres), "lon": LNG, "place_id": place_id}


def test_pick_match_accepts_close_and_similar() -> None:
    cand = _cand("Toronto General Hospital", 50)
    assert pick_match(FACILITY, [cand]) is cand


def test_pick_match_boundary_299_vs_301_metres() -> None:
    assert pick_match(FACILITY, [_cand("Toronto General Hospital", 299)]) is not None
    assert pick_match(FACILITY, [_cand("Toronto General Hospital", 301)]) is None


def test_pick_match_rejects_close_but_wrong_name() -> None:
    assert pick_match(FACILITY, [_cand("Sick Kids Pharmacy", 20)]) is None


def test_pick_match_rejects_right_name_far_away() -> None:
    assert pick_match(FACILITY, [_cand("Toronto General Hospital", 5000)]) is None


def test_pick_match_prefers_closest_valid() -> None:
    near = _cand("Toronto General Hospital", 30, "near")
    far = _cand("Toronto General Hospital", 200, "far")
    assert pick_match(FACILITY, [far, near]) is near


def test_pick_match_skips_candidate_without_coordinates_or_name() -> None:
    assert pick_match(FACILITY, [{"name": "Toronto General Hospital", "place_id": "x"}]) is None
    assert pick_match(FACILITY, [{"lat": LAT, "lon": LNG, "place_id": "x"}]) is None


def test_pick_match_none_for_no_candidates() -> None:
    assert pick_match(FACILITY, []) is None


# ── hours / gaps ──────────────────────────────────────────────────────────────

def test_hours_missing_values() -> None:
    assert is_hours_missing(None)
    assert is_hours_missing("")
    assert is_hours_missing("[]")
    assert is_hours_missing(" [] ")
    assert not is_hours_missing('["Mo-Su 06:00-23:00"]')


def test_needs_enrichment() -> None:
    full = {"phone": "+1-416-000-0000", "weekday_hours": '["24/7"]', "place_id": "abc"}
    assert not needs_enrichment(full)
    assert needs_enrichment({**full, "phone": None})
    assert needs_enrichment({**full, "phone": ""})
    assert needs_enrichment({**full, "weekday_hours": "[]"})
    assert needs_enrichment({**full, "place_id": None})


# ── build_patch ───────────────────────────────────────────────────────────────

DETAILS = {"contact": {"phone": "+1-416-340-4800"}, "opening_hours": "Mo-Fr 08:00-17:00"}


def test_patch_fills_all_gaps() -> None:
    fac = {"phone": None, "weekday_hours": "[]", "place_id": None}
    patch = build_patch(fac, DETAILS, "geo123")
    assert patch == {
        "phone": "+1-416-340-4800",
        "weekday_hours": json.dumps(["Mo-Fr 08:00-17:00"]),
        "place_id": "geo123",
    }


def test_patch_never_overwrites_existing_values() -> None:
    fac = {"phone": "+1-111", "weekday_hours": '["24/7"]', "place_id": "google-id"}
    assert build_patch(fac, DETAILS, "geo123") == {}


def test_patch_skips_empty_geoapify_values() -> None:
    fac = {"phone": None, "weekday_hours": "[]", "place_id": None}
    assert build_patch(fac, {"contact": {}, "opening_hours": None}, None) == {}
    assert build_patch(fac, {"contact": {"phone": "  "}}, "") == {}


def test_patch_phone_fallback_to_top_level_phone() -> None:
    fac = {"phone": None, "weekday_hours": '["24/7"]', "place_id": "x"}
    assert build_patch(fac, {"phone": "+1-905-111-2222"}, "geo") == {"phone": "+1-905-111-2222"}


# ── HTTP helpers (stubbed requests.get) ───────────────────────────────────────

import enrich_facilities_geoapify as mod  # noqa: E402
import pytest  # noqa: E402
import requests  # noqa: E402


class _Resp:
    def __init__(self, status: int, body: dict | None = None) -> None:
        self.status_code, self._body = status, body or {}

    def json(self) -> dict:
        return self._body

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}", response=self)


def _stub_get(monkeypatch: pytest.MonkeyPatch, responses: list[_Resp]) -> list[dict]:
    calls: list[dict] = []
    seq = iter(responses)

    def fake_get(url: str, params: dict, timeout: int) -> _Resp:
        calls.append({"url": url, "params": params})
        return next(seq)

    monkeypatch.setattr(mod.requests, "get", fake_get)
    monkeypatch.setattr(mod._limiter, "acquire", lambda: None)
    return calls


def test_get_retries_429_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _stub_get(monkeypatch, [_Resp(429), _Resp(200, {"features": []})])
    resp = mod.get_with_retry("u", {"apiKey": "SECRET"}, sleep=lambda s: None)
    assert resp.status_code == 200 and len(calls) == 2


def test_get_gives_up_after_max_retries_without_leaking_key(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _stub_get(monkeypatch, [_Resp(500)] * mod.MAX_RETRIES)
    with pytest.raises(RuntimeError) as exc:
        mod.get_with_retry("u", {"apiKey": "SECRET"}, sleep=lambda s: None)
    assert len(calls) == mod.MAX_RETRIES and "SECRET" not in str(exc.value)


def test_get_does_not_retry_client_error(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _stub_get(monkeypatch, [_Resp(401), _Resp(200)])
    with pytest.raises(RuntimeError, match="401"):
        mod.get_with_retry("u", {}, sleep=lambda s: None)
    assert len(calls) == 1


def test_search_candidates_returns_properties(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_get(monkeypatch, [_Resp(200, {"features": [{"properties": {"name": "X"}}, {"properties": {"name": "Y"}}]})])
    assert mod.search_candidates("k", {"name": "X", "address": "1 A St", "lat": 1.0, "lng": 2.0}) == [
        {"name": "X"}, {"name": "Y"}]


def test_search_candidates_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_get(monkeypatch, [_Resp(200, {"features": []})])
    assert mod.search_candidates("k", {"name": "X", "lat": 1.0, "lng": 2.0}) == []


def test_fetch_details_empty_features(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_get(monkeypatch, [_Resp(200, {"features": []})])
    assert mod.fetch_details("k", "pid") == {}


def test_enrich_one_unmatched_and_matched(monkeypatch: pytest.MonkeyPatch) -> None:
    fac = {"id": "f", "name": "Toronto General Hospital", "address": "", "lat": LAT, "lng": LNG,
           "phone": None, "weekday_hours": "[]", "place_id": None}
    monkeypatch.setattr(mod, "search_candidates", lambda k, f: [])
    assert mod.enrich_one("k", fac) == ("unmatched", {})

    cand = {"name": "Toronto General Hospital", "lat": LAT, "lon": LNG, "place_id": "geo1"}
    monkeypatch.setattr(mod, "search_candidates", lambda k, f: [cand])
    monkeypatch.setattr(mod, "fetch_details", lambda k, pid: {"contact": {"phone": "+1-416-340-4800"}})
    status, patch = mod.enrich_one("k", fac)
    assert status == "matched" and patch == {"phone": "+1-416-340-4800", "place_id": "geo1"}


# ── apply_patch against the local rehearsal DB (docker medicoord-demo-pg) ─────

import psycopg  # noqa: E402

LOCAL_DSN = "postgresql://postgres:postgres@localhost:5433/medicoord_demo"


@pytest.fixture()
def conn():
    try:
        c = psycopg.connect(LOCAL_DSN, connect_timeout=3)
    except psycopg.OperationalError:
        pytest.skip("local rehearsal DB not running")
    yield c
    c.rollback()  # every test runs inside one transaction that is never committed
    c.close()


def _insert(conn, name: str, lat: float, **cols) -> str:
    row = conn.execute(
        """insert into facilities (name, category, source_facility_type, accepted_severity, address, lat, lng,
                                   phone, weekday_hours, place_id)
           values (%s, 'ambulatory', 'clinic', array['routine'], 'x', %s, -79.0, %s, %s, %s) returning id::text""",
        (name, lat, cols.get("phone"), cols.get("weekday_hours"), cols.get("place_id")),
    ).fetchone()
    return row[0]


@pytest.mark.integration
def test_apply_patch_fills_gaps_and_keeps_existing(conn) -> None:
    fid = _insert(conn, "zz test clinic A", 10.001, phone="+1-existing", weekday_hours="[]")
    written = mod.apply_patch(conn, fid, {"phone": "+1-new", "weekday_hours": '["24/7"]', "place_id": "geo-a"})
    assert sorted(written) == ["place_id", "weekday_hours"]
    row = conn.execute("select phone, weekday_hours, place_id from facilities where id = %s", (fid,)).fetchone()
    assert row == ("+1-existing", '["24/7"]', "geo-a")


@pytest.mark.integration
def test_apply_patch_survives_place_id_collision(conn) -> None:
    _insert(conn, "zz test clinic B1", 10.002, place_id="dup")
    fid = _insert(conn, "zz test clinic B2", 10.003)
    written = mod.apply_patch(conn, fid, {"phone": "+1-555", "place_id": "dup"})
    assert written == ["phone"]
    row = conn.execute("select phone, place_id from facilities where id = %s", (fid,)).fetchone()
    assert row == ("+1-555", None)
