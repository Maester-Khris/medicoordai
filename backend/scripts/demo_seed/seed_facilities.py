"""One-time (re-runnable) facility seed for the demo database.

  export   Supabase REST (facilities_clean + a few columns of facilities) -> artifacts/demo-seed/*.json
           (git-ignored). Needs the Supabase env, so run it under Doppler:
               doppler run -- python backend/scripts/demo_seed/seed_facilities.py export
  load     the exported files -> the demo database, as the admin user (DATABASE_URL), upsert on id:
               python backend/scripts/demo_seed/seed_facilities.py load [--dry-run]

Normally driven through backend/script.demo.local.sh (`seed export`, `seed load`, with --local for
the docker rehearsal). Facility ids are kept as they are in Supabase, so Redis keys, Supabase
wait_times and the dual-writing worker all keep referring to the same facility.

Reuses backend/db.py's supabase_select (same helper as scripts/eval_seed/export_primary_data.py).
Only facility tables are touched; profile/sessions/messages/auth are never read.
"""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
REPO = BACKEND.parent
OUT = REPO / "artifacts" / "demo-seed"

CATEGORIES = {"hospital", "ambulatory", "residential"}
SEVERITIES = {"emergent", "urgent", "moderate", "routine"}
FILES = {"clean": OUT / "facilities_clean.json", "raw": OUT / "facilities_raw.json"}


# ── export ────────────────────────────────────────────────────────────────────

def export() -> None:
    sys.path.insert(0, str(BACKEND))
    from db import supabase_select  # needs SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY in the env

    clean = supabase_select("facilities_clean", {"select": "*"})
    raw = supabase_select("facilities", {"select": "id,source,created_at,updated_at"})
    for name, rows in (("facilities_clean", clean), ("facilities", raw)):
        if len(rows) in (1000, 10000):  # common PostgREST page limits: treat as truncated, not complete
            sys.exit(f"{name}: exactly {len(rows)} rows, probably truncated; add pagination before trusting this")

    OUT.mkdir(parents=True, exist_ok=True)
    FILES["clean"].write_text(json.dumps(clean, indent=1, sort_keys=True))
    FILES["raw"].write_text(json.dumps(raw, indent=1, sort_keys=True))
    (OUT / "manifest.json").write_text(json.dumps({
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "facilities_clean_rows": len(clean), "facilities_rows": len(raw),
    }, indent=1))
    print(f"exported {len(clean)} facilities_clean rows and {len(raw)} facilities rows -> {OUT}")


# ── validate ──────────────────────────────────────────────────────────────────

def _problems(r: dict) -> list[str]:
    out = []
    for k in ("facility_id", "facility_name", "source_facility_type", "address"):
        if not str(r.get(k) or "").strip():
            out.append(f"{k} is empty")
    if r.get("category") not in CATEGORIES:
        out.append(f"category {r.get('category')!r} not allowed")
    sev = r.get("accepted_severity")
    if not isinstance(sev, list) or not sev or not set(sev) <= SEVERITIES:
        out.append(f"accepted_severity {sev!r} invalid")
    for k, lo, hi in (("lat", -90, 90), ("lng", -180, 180)):
        v = r.get(k)
        if not isinstance(v, (int, float)) or not lo <= v <= hi:
            out.append(f"{k} {v!r} invalid")
    return out


def prepare(clean: list[dict], raw: list[dict]) -> tuple[list[dict], list[tuple[str, str]], list[str]]:
    """Returns (rows ready to insert, rejected [(name, reason)], warnings)."""
    extras = {r["id"]: r for r in raw}
    by_id: dict[str, dict] = {}
    for r in clean:  # clean has no primary key: keep the most recent dbt row per id
        cur = by_id.get(r["facility_id"])
        if cur is None or (r.get("dbt_run_at") or "") > (cur.get("dbt_run_at") or ""):
            by_id[r["facility_id"]] = r

    warnings: list[str] = []
    # A place_id shared by several facilities is an artefact of the old Google lookup and often a wrong
    # match. Keep it only on the single hospital in the group; otherwise drop it for the whole group
    # (the Geoapify enrichment will fill it in properly later).
    groups: dict[str, list[dict]] = {}
    for r in by_id.values():
        if r.get("google_place_id"):
            groups.setdefault(r["google_place_id"], []).append(r)
    keeper: dict[str, str | None] = {}
    for pid, members in groups.items():
        hospitals = [m for m in members if m.get("category") == "hospital"]
        keeper[pid] = members[0]["facility_id"] if len(members) == 1 else (hospitals[0]["facility_id"] if len(hospitals) == 1 else None)
    shared = [pid for pid, m in groups.items() if len(m) > 1]
    dropped_ids = sum(len(groups[p]) - (1 if keeper[p] else 0) for p in shared)
    if shared:
        warnings.append(f"{len(shared)} shared place_ids: kept on a hospital row where unambiguous, dropped from {dropped_ids} rows")

    ready, rejected = [], []
    seen_key = set()
    mismatch_operational = 0
    for r in sorted(by_id.values(), key=lambda x: x.get("facility_name") or ""):
        problems = _problems(r)
        key = (r.get("facility_name"), r.get("lat"), r.get("lng"))
        if not problems and key in seen_key:
            problems.append("duplicate (name, lat, lng)")
        if problems:
            rejected.append((str(r.get("facility_name")), "; ".join(problems)))
            continue
        seen_key.add(key)

        pid = r.get("google_place_id") or None
        place_id = pid if pid and keeper.get(pid) == r["facility_id"] else None

        status = r.get("business_status")
        if bool(r.get("is_operational")) != (str(status or "").upper() == "OPERATIONAL"):
            mismatch_operational += 1

        ex = extras.get(r["facility_id"], {})
        hours = r.get("weekday_hours")
        ready.append({
            "id": r["facility_id"], "name": r["facility_name"], "category": r["category"],
            "source_facility_type": r["source_facility_type"], "accepted_severity": r["accepted_severity"],
            "address": r["address"], "lat": float(r["lat"]), "lng": float(r["lng"]),
            "phone": r.get("phone"), "business_status": status,
            "weekday_hours": hours if hours is None or isinstance(hours, str) else json.dumps(hours),
            "place_id": place_id, "last_enriched_at": r.get("last_enriched_at"),
            "source": ex.get("source") or "odhf",
            "created_at": ex.get("created_at"), "updated_at": ex.get("updated_at"),
        })
    if len(clean) != len(by_id):
        warnings.append(f"{len(clean) - len(by_id)} duplicate facility_id row(s) in facilities_clean collapsed")
    if mismatch_operational:
        warnings.append(f"{mismatch_operational} row(s) where source is_operational differs from business_status")
    missing_extra = sum(1 for r in ready if r["id"] not in extras)
    if missing_extra:
        warnings.append(f"{missing_extra} row(s) not found in facilities (source defaulted to 'odhf')")
    return ready, rejected, warnings


# ── load ──────────────────────────────────────────────────────────────────────

UPSERT = """
insert into facilities (id, name, category, source_facility_type, accepted_severity, address, lat, lng,
                        phone, business_status, weekday_hours, place_id, last_enriched_at, source,
                        created_at, updated_at)
values (%(id)s::uuid, %(name)s, %(category)s, %(source_facility_type)s, %(accepted_severity)s, %(address)s,
        %(lat)s, %(lng)s, %(phone)s, %(business_status)s, %(weekday_hours)s, %(place_id)s,
        %(last_enriched_at)s::timestamptz, %(source)s,
        coalesce(%(created_at)s::timestamptz, now()), coalesce(%(updated_at)s::timestamptz, now()))
on conflict (id) do update set
    name = excluded.name, category = excluded.category, source_facility_type = excluded.source_facility_type,
    accepted_severity = excluded.accepted_severity, address = excluded.address, lat = excluded.lat,
    lng = excluded.lng, phone = excluded.phone, business_status = excluded.business_status,
    weekday_hours = excluded.weekday_hours, place_id = excluded.place_id,
    last_enriched_at = excluded.last_enriched_at, source = excluded.source
returning (xmax = 0) as inserted
"""


def load(dry_run: bool) -> None:
    for p in FILES.values():
        if not p.exists():
            sys.exit(f"{p} not found: run `export` first")
    clean = json.loads(FILES["clean"].read_text())
    raw = json.loads(FILES["raw"].read_text())
    ready, rejected, warnings = prepare(clean, raw)

    cats: dict[str, int] = {}
    for r in ready:
        cats[r["category"]] = cats.get(r["category"], 0) + 1
    print(f"source rows: {len(clean)} | ready: {len(ready)} | rejected: {len(rejected)} | by category: {cats}")
    for w in warnings:
        print("  warning:", w)
    for name, why in rejected:
        print(f"  REJECTED {name}: {why}")
    if dry_run:
        print("dry run: nothing written")
        return

    import psycopg
    dsn = os.environ.get("DATABASE_URL", "").replace("+psycopg", "", 1)
    if not dsn:
        sys.exit("DATABASE_URL is not set (use backend/script.demo.local.sh seed load)")
    with psycopg.connect(dsn, connect_timeout=8) as conn:
        inserted = updated = 0
        for r in ready:
            if conn.execute(UPSERT, r).fetchone()[0]:
                inserted += 1
            else:
                updated += 1
        total = conn.execute("select count(*) from facilities").fetchone()[0]
        db_cats = dict(conn.execute("select category, count(*) from facilities group by 1 order by 1").fetchall())
        operational = conn.execute("select count(*) from facilities where is_operational").fetchone()[0]
        ids_ok = conn.execute("select count(*) from facilities where id = any(%s::uuid[])",
                              ([r["id"] for r in ready],)).fetchone()[0]
    print(f"loaded: {inserted} inserted, {updated} updated | table now has {total} rows "
          f"({ids_ok}/{len(ready)} of the prepared ids present), by category {db_cats}, {operational} operational")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "export":
        export()
    elif cmd == "load":
        load("--dry-run" in sys.argv[2:])
    else:
        sys.exit(__doc__)
