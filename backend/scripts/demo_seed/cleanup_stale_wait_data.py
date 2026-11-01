"""One-off cleanup of wait-time data written by the old (pre-rewrite) scraper.

Keeps only HOSPITAL facilities (the ids in the demo DB, category 'hospital'):
  1. Supabase  wait_times  : delete rows whose facility_id is not a hospital id
  2. Redis     hash wait_times:current : HDEL fields that are not hospital ids
  3. Redis     set  scraper:unresolved_places : DEL (left over from the expired Google Places key)
The demo Postgres is NOT touched (wait_times there is hospital-only by composite FK).

Default is a dry run (counts only). Pass --apply to delete. Secrets are read from the environment
(Doppler: SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, UPSTASH_REDIS_URL; POSTGRES_DB_URL_WORKER) and never printed.
Run via: backend/script.demo.local.sh cleanup [--apply]
"""
from __future__ import annotations

import argparse
import os
import sys

import psycopg
import redis
import requests

REDIS_HASH_KEY = "wait_times:current"
REDIS_UNRESOLVED_KEY = "scraper:unresolved_places"
SUPABASE_BATCH = 100  # ids per DELETE (keeps the URL short)


def _env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        sys.exit(f"missing env var {name}")
    return value


def hospital_ids(dsn: str) -> set[str]:
    with psycopg.connect(dsn, connect_timeout=10) as conn:
        rows = conn.execute("select id::text from facilities where category = 'hospital'").fetchall()
    return {r[0] for r in rows}


def _sb_headers(key: str, **extra: str) -> dict[str, str]:
    return {"apikey": key, "Authorization": f"Bearer {key}", **extra}


def supabase_stale_ids(url: str, key: str, keep: set[str]) -> list[str]:
    """Distinct facility_ids present in Supabase wait_times that are not hospitals.

    Keyset (cursor) pagination on the primary key `id`: each page is `id > last_seen`, an index seek,
    instead of OFFSET which rescans all skipped rows.
    """
    seen: set[str] = set()
    last_id: str | None = None
    page = 1000
    while True:
        params = {"select": "id,facility_id", "order": "id.asc", "limit": page}
        if last_id is not None:
            params["id"] = f"gt.{last_id}"
        r = requests.get(f"{url}/rest/v1/wait_times", headers=_sb_headers(key), params=params, timeout=30)
        r.raise_for_status()
        batch = r.json()
        seen.update(row["facility_id"] for row in batch)
        if len(batch) < page:
            break
        last_id = str(batch[-1]["id"])
    return sorted(seen - keep)


def supabase_count(url: str, key: str, ids: list[str]) -> int:
    total = 0
    for i in range(0, len(ids), SUPABASE_BATCH):
        chunk = ",".join(ids[i:i + SUPABASE_BATCH])
        r = requests.get(
            f"{url}/rest/v1/wait_times", headers=_sb_headers(key, Prefer="count=exact", Range="0-0"),
            params={"select": "facility_id", "facility_id": f"in.({chunk})"}, timeout=30,
        )
        r.raise_for_status()
        total += int(r.headers["Content-Range"].split("/")[1])
    return total


def supabase_delete(url: str, key: str, ids: list[str]) -> None:
    for i in range(0, len(ids), SUPABASE_BATCH):
        chunk = ",".join(ids[i:i + SUPABASE_BATCH])
        requests.delete(
            f"{url}/rest/v1/wait_times", headers=_sb_headers(key, Prefer="return=minimal"),
            params={"facility_id": f"in.({chunk})"}, timeout=60,
        ).raise_for_status()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="actually delete (default: dry run)")
    args = ap.parse_args()

    keep = hospital_ids(_env("POSTGRES_DB_URL_WORKER"))
    print(f"hospital ids kept: {len(keep)}  mode: {'APPLY' if args.apply else 'DRY RUN'}")

    sb_url, sb_key = _env("SUPABASE_URL"), _env("SUPABASE_SERVICE_ROLE_KEY")
    stale_ids = supabase_stale_ids(sb_url, sb_key, keep)
    sb_rows = supabase_count(sb_url, sb_key, stale_ids) if stale_ids else 0
    print(f"supabase wait_times: {sb_rows} rows across {len(stale_ids)} non-hospital facility ids")

    client = redis.from_url(_env("UPSTASH_REDIS_URL"), decode_responses=True)
    stale_fields = [f for f in client.hkeys(REDIS_HASH_KEY) if f not in keep]
    unresolved = client.scard(REDIS_UNRESOLVED_KEY)
    print(f"redis {REDIS_HASH_KEY}: {len(stale_fields)} non-hospital fields of {client.hlen(REDIS_HASH_KEY)}")
    print(f"redis {REDIS_UNRESOLVED_KEY}: {unresolved} members")

    if not args.apply:
        print("dry run only; re-run with --apply to delete")
        return

    if stale_ids:
        supabase_delete(sb_url, sb_key, stale_ids)
        print(f"supabase: deleted {sb_rows} rows")
    if stale_fields:
        client.hdel(REDIS_HASH_KEY, *stale_fields)
        print(f"redis: removed {len(stale_fields)} hash fields")
    client.delete(REDIS_UNRESOLVED_KEY)
    print(f"redis: deleted set {REDIS_UNRESOLVED_KEY}")


if __name__ == "__main__":
    main()
