# Geoapify enrichment port to the demo database — design + implementation plan

Date: 2026-10-05 · Branch: `feat/guest-demo-core` · Sprint 20, Phase 0 item 4
Status: DRAFT, awaiting user review (design and plan live in this one file by request)

---

# Part 1 — Design

## 1. Problem

The 308 demo `facilities` rows were enriched earlier with Google Places (key now expired). The only
Geoapify enrichment code is [`pipeline/scripts/backfill_facilities_clean.py`](../../../pipeline/scripts/backfill_facilities_clean.py),
which reads and writes **Supabase** (`facilities` + a rebuilt `facilities_clean`). The demo database
has one `facilities` table (no `facilities_clean`), so the script cannot be reused as is, and it has
two known flaws:

- `business_status` is hardcoded `OPERATIONAL` (Geoapify returns no status), so closed places look open.
- The geocoder is called with `limit=1` and the result is accepted without validation, so a wrong
  address, phone or id can be attached to a facility.

## 2. Current data (demo DB, 2026-10-05)

| category | rows | place_id | phone | weekday_hours | business_status |
|---|---|---|---|---|---|
| hospital | 35 | 35 | 7 | 35 | 35 |
| ambulatory | 99 | 78 | 13 | 99 | 99 |
| residential | 174 | 163 | 14 | 174 | 174 |

Phone is the big gap (34 of 308 filled). Existing `place_id` values are Google ids; Geoapify's
place-details endpoint needs a Geoapify id, so existing ids cannot be reused for lookups.

## 3. Geoapify API facts (probed 2026-10-05, Toronto General)

- `GET /v1/geocode/search` (filter `countrycode:ca`, `limit` up to 5) returns name, `result_type`,
  `rank.confidence`, `lat`/`lon`, `place_id`.
- `GET /v2/place-details?id=<place_id>&features=details` returns `contact.phone`, `website`,
  `opening_hours` (OSM syntax, often absent), `categories`. No business status.
- Key env var: `GEOAPIFY_API_KEY` (present in the repo-root Doppler config, not in `workers/`).
- Free tier: 5 requests/second, about 3,000 credits/day. Worst case here is about 616 calls.

## 4. Decisions (user, 2026-10-05)

1. **Gap-fill only.** Fill NULL `phone`, `weekday_hours`, `place_id` from Geoapify. Never overwrite an
   existing value. Never touch `business_status`, `lat`, `lng`, `address`.
2. **Manual one-off CLI**, not part of the 15-minute worker and not a cron service. Lives under
   `backend/scripts/demo_seed/`, run through `script.demo.local.sh`, dry-run by default.
3. **Runs as the admin/owner role through the tunnel.** `medicoord_worker` stays select/insert only;
   no new migration, no new role.
4. **Validated matching.** Accept a geocoder candidate only if it is within 300 m of the stored
   lat/lng **and** passes a name-token overlap check. Otherwise log it as unmatched and skip.

## 5. Approach

New script `backend/scripts/demo_seed/enrich_facilities_geoapify.py`. The legacy Supabase script is
left untouched (a follow-up can delete it once the demo DB is the source of truth). Reasons for a new
file rather than editing the old one: different datastore (psycopg vs PostgREST), different
semantics (gap-fill vs overwrite), and the old one has no tests worth keeping.

Alternatives considered and rejected:

- *Edit the old script in place.* Keeps two incompatible behaviours in one file.
- *Run inside the worker.* Enrichment is rare and rate limited; the worker runs every 15 minutes.

## 6. Components

| Unit | Purpose | Depends on |
|---|---|---|
| `RateLimiter`, `get_with_retry` | 5 req/s cap, retry with backoff on 429/5xx | `requests` |
| `search_candidates(key, facility)` | geocode `name + address`, `limit=5`, `filter=countrycode:ca` | HTTP helpers |
| `haversine_m(lat1, lng1, lat2, lng2)` | distance in metres | none |
| `name_overlap(a, b)` | distinctive-token Jaccard after stopword removal | none |
| `pick_match(facility, candidates)` | first candidate within 300 m and overlap >= 0.5, else `None` | the two above |
| `fetch_details(key, place_id)` | place-details, returns phone/hours/website props | HTTP helpers |
| `build_patch(facility, details, place_id)` | only the columns that are NULL on the facility and non-empty in Geoapify | none |
| `apply_patch(conn, facility_id, patch)` | `UPDATE ... SET col = coalesce(col, %s)`; sets `last_enriched_at` when something was filled | psycopg |
| `main()` | select candidates, loop, report, `--apply` / `--limit` / `--category` | all |

Pure functions (`haversine_m`, `name_overlap`, `pick_match`, `build_patch`) carry the logic and are
unit tested without network or database.

## 7. Data flow

1. Select candidate facilities: any of `phone`, `weekday_hours`, `place_id` is NULL. Optional
   `--category hospital` and `--limit N` for staged runs.
2. For each: geocode search -> `pick_match` -> if none, record `unmatched` and continue.
3. Place-details for the matched Geoapify id -> `build_patch`.
4. Dry run: print per-facility planned patch and a summary. `--apply`: write each patch in its own
   short transaction.
5. Summary: matched, unmatched, filled counts per column, skipped on id conflict, errors.

## 8. Error handling

- HTTP 429/5xx: retry with backoff (3 attempts); then log and skip that facility.
- `place_id` has a partial unique index. Two facilities mapping to one Geoapify place raises a
  unique violation; catch per row, skip the `place_id` column for that facility, keep phone/hours.
- A single failing facility never aborts the run. Exit code 1 if any error occurred.
- Never print the API key or database URLs.

## 9. Open items (resolved during implementation)

- Existing `weekday_hours` format: sample the 308 rows first and normalise Geoapify's OSM
  `opening_hours` to the same shape (or store the raw string if existing rows use it).
- Phone format: store as Geoapify returns (`+1-416-340-4800`) unless existing rows differ.
- `business_status` stays as is; sourcing real status (for example from the OSM tag or a manual
  list) is out of scope here and noted as a follow-up.

## 10. Testing

Unit tests for the four pure functions (boundary cases: 299 m / 301 m, empty names, stopwords only,
NULL vs empty values). Integration check against the local rehearsal DB (`--local`) with a stubbed
HTTP layer. One live dry run on `--category hospital --limit 5` before any `--apply`.

## 11. Out of scope

Supabase writes, `facilities_clean`, business status, address/coordinate changes, scheduling.

---

# Part 2 — Implementation plan

Conventions: Python venv `source /home/niki/Documents/workenv/pydev/bin/activate`; Doppler from the
repo root for `GEOAPIFY_API_KEY`; no new dependencies (`requests`, `psycopg` already present). Nothing
is committed or applied to the remote DB without explicit approval.

## Task 1 — Sample existing formats (read-only)

- [ ] `script.demo.local.sh query "select weekday_hours, phone from facilities where weekday_hours is not null limit 15"`
- [ ] Record the observed shapes in section 9 of this file and decide the normalisation.

## Task 2 — Pure functions, tests first

Files: `backend/scripts/demo_seed/enrich_facilities_geoapify.py` (new),
`backend/tests/test_enrich_facilities_geoapify.py` (new).

- [ ] Write failing tests for `haversine_m`, `name_overlap`, `pick_match`, `build_patch`.
- [ ] Run `pytest backend/tests/test_enrich_facilities_geoapify.py -q`; expect failures.
- [ ] Implement the four functions; rerun; expect pass.

## Task 3 — HTTP helpers

- [ ] Add `RateLimiter` and `get_with_retry`, ported from the legacy script (5 req/s, retries).
- [ ] Add `search_candidates` and `fetch_details`; test with a stubbed `requests.get`
      (success, empty features, 429 then success, persistent 500).

## Task 4 — Database layer and CLI

- [ ] `select_candidates(conn, category, limit)`; `apply_patch(conn, id, patch)` using
      `coalesce(col, %s)` so existing values are never overwritten; per-row unique-violation handling.
- [ ] `main()` with `--apply` (default dry run), `--limit`, `--category`; summary and exit code.
- [ ] Test `apply_patch` against the local rehearsal DB: fills NULLs, keeps existing values,
      survives a `place_id` collision.

## Task 5 — Wrapper command

- [ ] Add `enrich [--apply] [--limit N] [--category C]` to `backend/script.demo.local.sh`
      (git-ignored): admin URL via the tunnel, `doppler run` from the repo root, typed `yes`
      before `--apply`.

## Task 6 — Rehearse, then stage

- [ ] `--local` dry run on all candidates; review the unmatched list.
- [ ] `--local --apply`; check counts and that no existing value changed.
- [ ] Remote dry run `--category hospital --limit 5`; show the user the planned patches.
- [ ] With user approval: remote `--apply` for hospitals, then the rest.

## Task 7 — Commit (with approval)

- [ ] One commit: `feat: add geoapify gap-fill enrichment for demo facilities` (script + tests).
- [ ] Update the Sprint 20 changelog entry.
- [ ] Do not push until asked.

## Verification before claiming done

Tests pass; dry run and local apply output reviewed; row counts compared before and after
(`phone` NULL count drops, no value changes on previously filled columns).
