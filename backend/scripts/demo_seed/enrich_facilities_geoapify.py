"""Gap-fill demo `facilities` from Geoapify (phone, weekday_hours, place_id).

Rules (see docs/superpowers/specs/2026-10-05-geoapify-demo-enrichment-port-design.md):
  * gap-fill only: an existing value is never overwritten (UPDATE ... coalesce / empty-hours check)
  * business_status, lat, lng, address are never touched (Geoapify returns no status)
  * a geocoder result is accepted only if within MAX_DISTANCE_M of the stored lat/lng AND the
    distinctive-name overlap is >= MIN_NAME_OVERLAP; otherwise the facility is reported as unmatched
  * dry run by default; --apply writes, one short transaction per facility

Env: DATABASE_URL (admin, set by script.demo.local.sh) and GEOAPIFY_API_KEY (from backend/.env.demo.local).
Run via: backend/script.demo.local.sh [--local] enrich [--apply] [--limit N] [--category C]
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import logging
import math
import os
import re
import sys
import threading
import time
from collections import deque
from typing import Any

import psycopg
import requests

log = logging.getLogger("enrich_facilities_geoapify")

GEOCODE_URL = "https://api.geoapify.com/v1/geocode/search"
DETAILS_URL = "https://api.geoapify.com/v2/place-details"

MAX_DISTANCE_M = 300.0       # street number confirmed
MIN_NAME_OVERLAP = 0.5
# No street number on one side (e.g. a campus or area result): the address cannot confirm the match,
# so require a tight radius and a near-exact name. Added after "Kingsway" and "University of Toronto"
# were filled with another place's phone / hours.
MAX_DISTANCE_UNCONFIRMED_M = 100.0
MIN_NAME_JACCARD_UNCONFIRMED = 0.75
MAX_RETRIES = 3
REQUESTS_PER_SECOND = 5  # Geoapify free tier

# Generic words that appear in many facility names; same idea as workers/scraper.py STOP_WORDS.
STOP_WORDS = frozenset(
    """hospital hospitals health healthcare centre center centres clinic clinics care services service
    system network site campus st saint sainte the of and inc ltd retirement residence residences home
    homes long term lodge manor medical s""".split()
)
CATEGORIES = ("hospital", "ambulatory", "residential")


# ── pure functions ────────────────────────────────────────────────────────────

def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in metres."""
    r = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _normalize(name: str | None) -> str:
    n = (name or "").lower().replace("’", "").replace("'", "")
    return " ".join(re.sub(r"[^a-z0-9\s]", " ", n).split())


def _distinctive(name: str | None) -> frozenset[str]:
    return frozenset(w for w in _normalize(name).split() if w not in STOP_WORDS and len(w) > 1)


def name_overlap(a: str | None, b: str | None) -> float:
    """Shared distinctive words / size of the smaller set (0.0 if either has none).

    Overlap coefficient rather than Jaccard so that "Toronto General Hospital" still matches
    "University Health Network - Toronto General Hospital"; the distance check guards the rest.
    """
    wa, wb = _distinctive(a), _distinctive(b)
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / min(len(wa), len(wb))


def _house_number(address: str | None) -> str | None:
    """Leading street number of 'a/b street' style addresses, e.g. '4251 dundas street w' -> '4251'."""
    m = re.match(r"\s*(\d+[a-z]?)\b", (address or "").lower())
    return m.group(1) if m else None


def name_jaccard(a: str | None, b: str | None) -> float:
    wa, wb = _distinctive(a), _distinctive(b)
    return len(wa & wb) / len(wa | wb) if wa and wb else 0.0


def pick_match(facility: dict[str, Any], candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Closest acceptable candidate, or None.

    Street number on both sides: must be equal, within MAX_DISTANCE_M, name overlap >= MIN_NAME_OVERLAP.
    Otherwise (unconfirmed): within MAX_DISTANCE_UNCONFIRMED_M and name Jaccard >= MIN_NAME_JACCARD_UNCONFIRMED.
    """
    fac_no = _house_number(facility.get("address"))
    best: tuple[float, dict[str, Any]] | None = None
    for c in candidates:
        if c.get("lat") is None or c.get("lon") is None or not c.get("name"):
            continue
        dist = haversine_m(facility["lat"], facility["lng"], c["lat"], c["lon"])
        cand_no = (c.get("housenumber") or "").strip().lower() or None
        if fac_no and cand_no:
            if fac_no != cand_no or dist > MAX_DISTANCE_M or name_overlap(facility["name"], c["name"]) < MIN_NAME_OVERLAP:
                continue
        elif dist > MAX_DISTANCE_UNCONFIRMED_M or name_jaccard(facility["name"], c["name"]) < MIN_NAME_JACCARD_UNCONFIRMED:
            continue
        if best is None or dist < best[0]:
            best = (dist, c)
    return best[1] if best else None


def is_hours_missing(value: str | None) -> bool:
    """weekday_hours is a JSON-array text; '[]' (empty) counts as missing."""
    return value is None or value.strip() in ("", "[]")


def needs_enrichment(facility: dict[str, Any]) -> bool:
    return (
        not (facility.get("phone") or "").strip()
        or is_hours_missing(facility.get("weekday_hours"))
        or not (facility.get("place_id") or "").strip()
    )


def build_patch(facility: dict[str, Any], details: dict[str, Any], place_id: str | None) -> dict[str, str]:
    """Only the columns that are empty on the facility and non-empty in Geoapify."""
    patch: dict[str, str] = {}

    phone = ((details.get("contact") or {}).get("phone") or details.get("phone") or "").strip()
    if phone and not (facility.get("phone") or "").strip():
        patch["phone"] = phone

    hours = details.get("opening_hours")
    if isinstance(hours, str) and hours.strip() and is_hours_missing(facility.get("weekday_hours")):
        patch["weekday_hours"] = json.dumps([hours.strip()])  # same shape as existing rows

    if place_id and place_id.strip() and not (facility.get("place_id") or "").strip():
        patch["place_id"] = place_id.strip()
    return patch


# ── HTTP ──────────────────────────────────────────────────────────────────────

class RateLimiter:
    def __init__(self, max_per_sec: int) -> None:
        self._max, self._lock, self._stamps = max_per_sec, threading.Lock(), deque()

    def acquire(self) -> None:
        with self._lock:
            now = time.monotonic()
            while self._stamps and now - self._stamps[0] >= 1.0:
                self._stamps.popleft()
            if len(self._stamps) >= self._max:
                time.sleep(max(0.0, 1.0 - (now - self._stamps[0])))
            self._stamps.append(time.monotonic())


_limiter = RateLimiter(REQUESTS_PER_SECOND)


def get_with_retry(url: str, params: dict[str, Any], *, sleep=time.sleep) -> requests.Response:
    """GET with the rate limiter; retries 429/5xx with backoff, raises after MAX_RETRIES."""
    last: Exception | None = None
    for attempt in range(MAX_RETRIES):
        _limiter.acquire()
        try:
            resp = requests.get(url, params=params, timeout=15)
        except requests.RequestException as exc:  # network error: retry
            last = exc
        else:
            if resp.status_code == 429 or resp.status_code >= 500:
                last = requests.HTTPError(f"HTTP {resp.status_code}")
            elif resp.status_code >= 400:  # bad key / bad request: retrying cannot help
                raise RuntimeError(f"Geoapify request rejected: HTTP {resp.status_code}")
            else:
                return resp
        if attempt < MAX_RETRIES - 1:
            sleep(2 ** attempt)
    raise RuntimeError(f"Geoapify request failed after {MAX_RETRIES} attempts: {type(last).__name__}")  # no params: key


def search_candidates(api_key: str, facility: dict[str, Any]) -> list[dict[str, Any]]:
    text = f"{facility['name']} {facility.get('address') or ''}".strip()
    resp = get_with_retry(
        GEOCODE_URL,
        {"text": text, "apiKey": api_key, "limit": 5, "filter": "countrycode:ca",
         "bias": f"proximity:{facility['lng']},{facility['lat']}"},
    )
    return [f.get("properties", {}) for f in resp.json().get("features", [])]


def fetch_details(api_key: str, place_id: str) -> dict[str, Any]:
    resp = get_with_retry(DETAILS_URL, {"id": place_id, "features": "details", "apiKey": api_key})
    features = resp.json().get("features", [])
    return features[0].get("properties", {}) if features else {}


# ── database ──────────────────────────────────────────────────────────────────

SELECT_FACILITIES = """
    select id::text as id, name, category, address, lat, lng, phone, weekday_hours, place_id
    from facilities
    where (%(category)s::text is null or category = %(category)s)
    order by category, name
"""


def select_candidates(conn: psycopg.Connection, category: str | None, limit: int | None) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
        cur.execute(SELECT_FACILITIES, {"category": category})
        rows = [r for r in cur.fetchall() if needs_enrichment(r)]
    return rows[:limit] if limit else rows


def apply_patch(conn: psycopg.Connection, facility_id: str, patch: dict[str, str]) -> list[str]:
    """Write the patch without ever overwriting a value; returns the columns actually written.

    Each column is its own UPDATE so a place_id unique-index collision cannot lose phone/hours.
    """
    written: list[str] = []
    for col, value in patch.items():
        if col == "weekday_hours":
            cond = "(weekday_hours is null or btrim(weekday_hours) in ('', '[]'))"
        else:
            cond = f"({col} is null or btrim({col}) = '')"
        try:
            with conn.transaction():
                cur = conn.execute(
                    f"update facilities set {col} = %s, last_enriched_at = now() "  # col is from a fixed set
                    f"where id = %s and {cond}",
                    (value, facility_id),
                )
                if cur.rowcount:
                    written.append(col)
        except psycopg.errors.UniqueViolation:
            log.warning("facility %s: place_id already used by another facility, skipped", facility_id)
    return written


# ── main ──────────────────────────────────────────────────────────────────────

def enrich_one(api_key: str, facility: dict[str, Any]) -> tuple[str, dict[str, str], str]:
    """Returns (status, patch, matched_name); status in matched | unmatched | nothing_new."""
    match = pick_match(facility, search_candidates(api_key, facility))
    if match is None:
        return "unmatched", {}, ""
    geo_id = match.get("place_id")
    details = fetch_details(api_key, geo_id) if geo_id else {}
    patch = build_patch(facility, details or match, geo_id)
    return ("matched" if patch else "nothing_new"), patch, match.get("name", "")


def resolve_place_id_conflicts(results: list[tuple[dict[str, Any], dict[str, str], str]], taken: set[str]) -> list[str]:
    """Several facilities can geocode to the same Geoapify place (e.g. two agencies in one building).
    Only the facility whose name is closest to the geocoded name keeps the place_id; the rest lose it from
    their patch. Ids already used in the database (`taken`) are dropped too. Returns dropped facility ids.
    """
    best: dict[str, tuple[float, str]] = {}
    for fac, patch, matched_name in results:
        pid = patch.get("place_id")
        if pid:
            score = name_jaccard(fac["name"], matched_name)
            if pid not in best or score > best[pid][0]:
                best[pid] = (score, fac["id"])
    dropped = []
    for fac, patch, _ in results:
        pid = patch.get("place_id")
        if pid and (pid in taken or best[pid][1] != fac["id"]):
            del patch["place_id"]
            dropped.append(fac["id"])
    return dropped


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="write to the database (default: dry run)")
    ap.add_argument("--limit", type=int, default=None, help="max facilities to process")
    ap.add_argument("--category", choices=CATEGORIES, default=None)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    api_key = os.environ.get("GEOAPIFY_API_KEY", "").strip()
    dsn = os.environ.get("DATABASE_URL", "").replace("+psycopg", "", 1)
    if not api_key:
        sys.exit("GEOAPIFY_API_KEY is not set (put it in backend/.env.demo.local)")
    if not dsn:
        sys.exit("DATABASE_URL is not set (use backend/script.demo.local.sh enrich)")

    stats = {"matched": 0, "unmatched": 0, "nothing_new": 0, "errors": 0}
    filled = {"phone": 0, "weekday_hours": 0, "place_id": 0}
    unmatched: list[str] = []

    os.makedirs("artifacts", exist_ok=True)
    out_file = "artifacts/geoapify_enrichment_results.jsonl"  # git-ignored; written after resolution

    with psycopg.connect(dsn, connect_timeout=10) as conn:
        facilities = select_candidates(conn, args.category, args.limit)
        log.info("%d facilities with a gap (%s)", len(facilities), "APPLY" if args.apply else "DRY RUN")

        taken = {r[0] for r in conn.execute("select place_id from facilities where place_id is not null").fetchall()}

        def _process(fac: dict[str, Any]) -> tuple[dict[str, Any], str, dict[str, str], str, Exception | None]:
            try:
                status, patch, matched_name = enrich_one(api_key, fac)
                return fac, status, patch, matched_name, None
            except Exception as e:
                return fac, "error", {}, "", e

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            outcomes = list(executor.map(_process, facilities))

        matched_rows = []
        for fac, status, patch, matched_name, exc in outcomes:
            if exc:
                stats["errors"] += 1
                log.error("%s: %s", fac["name"], exc)
            elif status == "unmatched":
                stats["unmatched"] += 1
                unmatched.append(fac["name"])
            else:
                stats[status] += 1
                matched_rows.append((fac, patch, matched_name))
        for fid in resolve_place_id_conflicts(matched_rows, taken):
            log.warning("facility %s: place_id dropped (already used or better match elsewhere)", fid)

        with open(out_file, "w") as f:
            for fac, status, patch, matched_name, exc in outcomes:
                final = next((p for ff, p, _ in matched_rows if ff["id"] == fac["id"]), patch)
                f.write(json.dumps({"facility_id": fac["id"], "name": fac["name"], "status": status,
                                    "matched_name": matched_name, "patch": final}) + "\n")

        for fac, patch, _ in matched_rows:
            if not patch:
                continue
            written = apply_patch(conn, fac["id"], patch) if args.apply else list(patch)
            for col in written:
                filled[col] += 1
            log.info("%s: %s", fac["name"], {k: patch[k] for k in written} or "no change")

    print(f"summary: {stats}")
    print(f"columns {'filled' if args.apply else 'that would be filled'}: {filled}")
    print(f"per-facility results: {out_file}")
    if unmatched:
        print(f"unmatched ({len(unmatched)}): " + "; ".join(unmatched[:40]) + (" ..." if len(unmatched) > 40 else ""))
    if not args.apply:
        print("dry run only; re-run with --apply to write")
    if stats["errors"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
