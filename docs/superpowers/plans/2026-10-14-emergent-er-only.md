# Emergent Cases Only to Facilities With an ER: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Emergent cases are only ever recommended a facility with an emergency department, on the live demo and after any re-seed.

**Architecture:** One reviewed list (`emergency_departments.json`) is the single source of which facilities take emergent cases. The seed loader applies it on every load; a one-time update statement generated from the same list fixes both databases now. The API reads facilities only at startup, so `python-api` is restarted after the remote update.

**Tech Stack:** Python 3.11 (pydev venv), psycopg 3, Postgres (`facilities.accepted_severity text[]`), pytest, Railway CLI, `backend/script.demo.local.sh`.

**Spec:** `docs/superpowers/specs/2026-10-14-emergent-er-routing-and-llm-budget-design.md` (part 1)

## Global Constraints

- Severity values: exactly `emergent`, `urgent`, `moderate`, `routine` (`shared/types.ts`).
- Hospital with an ER: `{emergent,urgent,moderate,routine}`. Hospital without: `{urgent,moderate,routine}`. Other categories: unchanged.
- `category` is never changed (the wait-time worker selects `category = 'hospital'`).
- Python only from `/home/niki/Documents/workenv/pydev/` (`source /home/niki/Documents/workenv/pydev/bin/activate`).
- Branch `fix/emergent-er-only` cut from `preview`. One-line conventional commits, files staged by name, no AI attribution, every commit shown to the owner first.
- Non-SELECT statements on the remote database are run by the owner through the tunnel.
- Secrets are never printed.

## Review Focus

- A listed id that is not a hospital in the load (stale or mistyped id): the loader must say so, not silently ignore it. Test in Task 2.
- A missing or empty ER list: the loader must stop, not fall back to the old rule or strip emergent from every hospital. Test in Task 2.
- A hospital whose source row says `emergent` but is not listed: it must lose `emergent`. Test in Task 2.
- The update statement touching a non-hospital row: the `where category = 'hospital'` guard and the before/after counts in Tasks 3 and 4.
- A real ER left off the list: emergent cases go to the next ER. Accepted trade-off; the grid check in Task 3 shows where.

---

### Task 1: Build the ER list from the scraper's matches

**Files:**
- Create: `artifacts/demo-seed/er_match_report.py` (untracked, a one-off)
- Create: `backend/scripts/demo_seed/emergency_departments.json`

**Interfaces:**
- Produces: `emergency_departments.json` with shape `{"_about": str, "facilities": [{"id": uuid str, "name": str, "evidence": str}]}`. Task 2 reads `facilities[*].id`.

- [ ] **Step 1: Write the report script**

```python
"""Hospitals the wait-time sources match (ERs by evidence), and every scraped name that did not match.
Read-only: local docker database, public wait-time pages. Run from the repository root."""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "workers"))
import scraper  # noqa: E402

DSN = "postgresql://postgres:postgres@localhost:5433/medicoord_demo"

hospitals = scraper.read_hospitals(DSN)
rows = scraper.scrape_erstat() + scraper.scrape_howlongwilliwait()
matched = scraper.match_to_hospitals(rows, hospitals, scraper.load_aliases())
names = {h["id"]: h["name"] for h in hospitals}
ids = sorted({m["facility_id"] for m in matched})
print(f"{len(hospitals)} hospitals, {len(rows)} scraped rows, {len(ids)} hospitals matched")
for fid in ids:
    print(f"MATCHED    {fid}  {names[fid]}")
known = {scraper.normalize(m["name"]) for m in matched}
for name in sorted({r["name"] for r in rows if scraper.normalize(r["name"]) not in known}):
    print(f"UNMATCHED  {name}")
```

- [ ] **Step 2: Run it**

Run (repository root): `source /home/niki/Documents/workenv/pydev/bin/activate && python artifacts/demo-seed/er_match_report.py | tee artifacts/demo-seed/2026-10-14-er-match-report.txt`
Expected: a first line like `52 hospitals, N scraped rows, 11 hospitals matched` (the 11 that have wait data today), `MATCHED` lines, then `UNMATCHED` lines covering all of Ontario.

- [ ] **Step 3: Review the unmatched names with the owner**

Pick out the Toronto-area names among `UNMATCHED`. For each, decide with the owner: an ER we hold under another name (add it, evidence `"reviewed 2026-10-14: <scraped name>"`), or an ER we do not hold (skip, note it in the commit's PR description later). Candidates already seen: North York General, St. Joseph's Health Centre, Toronto East General (Michael Garron), Cortellucci Vaughan.

- [ ] **Step 4: Write the list**

One entry per `MATCHED` line plus each accepted reviewed name. Shape:

```json
{
  "_about": "Facilities with an emergency department: the only ones that accept emergent cases. Built 2026-10-14 from the wait-time scraper's matches plus names reviewed with the owner. The scraper never adds to this list by itself.",
  "facilities": [
    {"id": "<facility uuid from the report>", "name": "Mount Sinai Hospital", "evidence": "wait-time match 2026-10-14"}
  ]
}
```

No commit yet: the list is committed with the loader in Task 2.

### Task 2: The loader applies the list on every load

**Files:**
- Modify: `backend/scripts/demo_seed/seed_facilities.py` (constants near the top; `prepare` at line 72; `load` at line 166)
- Test: `backend/tests/test_seed_facilities.py` (new)

**Interfaces:**
- Consumes: `emergency_departments.json` from Task 1.
- Produces: `load_emergency_department_ids(path: Path = ER_LIST) -> frozenset[str]`, `accepted_severity_for(row: dict, er_ids: frozenset[str]) -> list[str]`, `prepare(clean, raw, er_ids: frozenset[str])` (new third argument). Task 3 reuses `ALL_SEVERITIES` and `NON_EMERGENT` values in its SQL.

- [ ] **Step 1: Branch**

```bash
cd /home/niki/Documents/saas/medicoordai && git fetch origin && git switch -c fix/emergent-er-only origin/preview
```

- [ ] **Step 2: Write the failing tests**

```python
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
```

- [ ] **Step 3: Run them to see them fail**

Run: `cd backend && source /home/niki/Documents/workenv/pydev/bin/activate && doppler run -- pytest tests/test_seed_facilities.py -v`
Expected: FAIL at import: `cannot import name 'ALL_SEVERITIES'`.

- [ ] **Step 4: Implement**

In `seed_facilities.py`, after `FILES = {...}`:

```python
ER_LIST = Path(__file__).resolve().parent / "emergency_departments.json"
ALL_SEVERITIES = ["emergent", "urgent", "moderate", "routine"]
NON_EMERGENT = ["urgent", "moderate", "routine"]


def load_emergency_department_ids(path: Path = ER_LIST) -> frozenset[str]:
    """Ids of the facilities with an emergency department. Stops on a missing or empty list:
    loading without it would silently keep or strip emergent on every hospital."""
    ids = frozenset(entry["id"] for entry in json.loads(path.read_text()).get("facilities", []))
    if not ids:
        sys.exit(f"{path}: no facilities listed")
    return ids


def accepted_severity_for(row: dict, er_ids: frozenset[str]) -> list[str]:
    """Emergent goes only to hospitals with an emergency department; other categories keep the source."""
    if row["category"] != "hospital":
        return row["accepted_severity"]
    return list(ALL_SEVERITIES if row["facility_id"] in er_ids else NON_EMERGENT)  # a copy: rows must not share one list
```

In `prepare`, change the signature and the `accepted_severity` field, and add the warning before `return`:

```python
def prepare(clean: list[dict], raw: list[dict], er_ids: frozenset[str]) -> tuple[list[dict], list[tuple[str, str]], list[str]]:
```

```python
            "source_facility_type": r["source_facility_type"], "accepted_severity": accepted_severity_for(r, er_ids),
```

```python
    hospital_ids = {r["id"] for r in ready if r["category"] == "hospital"}
    stray = er_ids - hospital_ids
    if stray:
        warnings.append(f"{len(stray)} listed ER id(s) are not hospitals in this load: {sorted(stray)}")
    return ready, rejected, warnings
```

In `load`:

```python
    ready, rejected, warnings = prepare(clean, raw, load_emergency_department_ids())
```

- [ ] **Step 5: Run the tests**

Run: `cd backend && doppler run -- pytest tests/test_seed_facilities.py -v`
Expected: 6 passed.

- [ ] **Step 6: Run the whole backend suite**

Run: `cd backend && doppler run -- pytest -q`
Expected: all passed (877 on `feat/demo-scaling`; the count on `preview` may differ), none failed.

- [ ] **Step 7: Dry-run the loader on the local copy**

Run: `cd backend && ./script.demo.local.sh --local seed load --dry-run`
Expected: `ready: 308`, no `listed ER id(s) are not hospitals` warning, `dry run: nothing written`.

- [ ] **Step 8: Commit (show the diff to the owner first)**

```bash
git add backend/scripts/demo_seed/emergency_departments.json backend/scripts/demo_seed/seed_facilities.py backend/tests/test_seed_facilities.py
git commit -m "fix(seed): give emergent only to facilities with an emergency department"
```

### Task 3: Fix the local copy and check it

**Files:**
- Create: `artifacts/demo-seed/emergent_grid_check.py` (untracked)
- Create: `artifacts/demo-seed/2026-10-14-hospital-severity-backup-local.json` (untracked)

**Interfaces:**
- Consumes: `emergency_departments.json`; `services.proximity.find_nearest_facilities`, `cache.set_cached_facilities`.
- Produces: the update statement Task 4 runs on the remote, in `artifacts/demo-seed/2026-10-14-emergent-update.sql`.

- [ ] **Step 1: Back up the hospital severities**

```bash
cd backend && ./script.demo.local.sh --local query "select coalesce(json_agg(json_build_object('id', id, 'accepted_severity', accepted_severity)), '[]')::text from facilities where category = 'hospital'" | tail -n +2 > ../artifacts/demo-seed/2026-10-14-hospital-severity-backup-local.json
```

Expected: one JSON array, one entry per hospital.

- [ ] **Step 2: Generate the statement from the list**

```bash
cd backend && source /home/niki/Documents/workenv/pydev/bin/activate && python - > ../artifacts/demo-seed/2026-10-14-emergent-update.sql <<'EOF'
import json
ids = [e["id"] for e in json.load(open("scripts/demo_seed/emergency_departments.json"))["facilities"]]
listed = ",".join(f"'{i}'" for i in ids)
print(f"update facilities set accepted_severity = case when id = any(array[{listed}]::uuid[]) "
      "then array['emergent','urgent','moderate','routine'] else array['urgent','moderate','routine'] end "
      "where category = 'hospital'")
EOF
cat ../artifacts/demo-seed/2026-10-14-emergent-update.sql
```

- [ ] **Step 3: Count before**

```bash
IDS=$(python -c "import json; print(','.join(\"'%s'\" % e['id'] for e in json.load(open('scripts/demo_seed/emergency_departments.json'))['facilities']))")
./script.demo.local.sh --local query "select count(*) as hospitals, count(*) filter (where id = any(array[$IDS]::uuid[])) as listed_found from facilities where category = 'hospital'"
```

Expected: `listed_found` equals the number of entries in the list. If lower, a listed id is wrong: stop and fix the list.

- [ ] **Step 4: Apply locally**

Run: `./script.demo.local.sh --local -y query "$(cat ../artifacts/demo-seed/2026-10-14-emergent-update.sql)"`
Expected: `OK (<number of hospitals> rows affected)`.

- [ ] **Step 5: Check the database**

Run: `./script.demo.local.sh --local query "select name from facilities where 'emergent' = any(accepted_severity) order by 1"`
Expected: exactly the names in the list. No rehabilitation centre, hospice, CAMH, surgical unit or cosmetic surgery row.

- [ ] **Step 6: Write the grid check**

```python
"""Nearest emergent facility over a Toronto grid: every one must be on the ER list. Local database."""
import json
import math
import sys
from pathlib import Path

import psycopg

REPO = Path(__file__).resolve().parents[2]
DSN = "postgresql://postgres:postgres@localhost:5433/medicoord_demo"
er_ids = {e["id"] for e in json.loads((REPO / "backend/scripts/demo_seed/emergency_departments.json").read_text())["facilities"]}

with psycopg.connect(DSN) as conn:
    rows = conn.execute("select id::text, name, lat, lng from facilities where 'emergent' = any(accepted_severity)").fetchall()


def km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lng2 - lng1) / 2) ** 2
    return 12742 * math.asin(math.sqrt(a))


points = [(43.60 + i * 0.01, -79.60 + j * 0.01) for i in range(26) for j in range(46)]
off_list = [(p, name) for p in points
            for fid, name, lat, lng in [min(rows, key=lambda r: km(p[0], p[1], r[2], r[3]))] if fid not in er_ids]
print(f"{len(points)} points, {len(off_list)} sent to a facility not on the ER list")
sys.exit(1 if off_list else 0)
```

- [ ] **Step 7: Run it**

Run (repository root): `python artifacts/demo-seed/emergent_grid_check.py`
Expected: `1196 points, 0 sent to a facility not on the ER list`, exit 0 (16% before the fix).

- [ ] **Step 8: Check the routing function itself at the chest-pain point**

```bash
cd backend && python - <<'EOF'
import psycopg
from psycopg.rows import dict_row
from cache import set_cached_facilities
from services.proximity import find_nearest_facilities
with psycopg.connect("postgresql://postgres:postgres@localhost:5433/medicoord_demo", row_factory=dict_row) as conn:
    set_cached_facilities(conn.execute("select id::text, name, category, accepted_severity, lat, lng from facilities").fetchall())
print([f["name"] for f in find_nearest_facilities(43.70, -79.40, "emergent", top_n=3)])
EOF
```

Expected: three names from the ER list; not "Toronto Rehabilitation Institute - Hillcrest Centre".

### Task 4: Fix the remote demo database and check it live

**Files:** none in the repository. Backup: `artifacts/demo-seed/2026-10-14-hospital-severity-backup-remote.json`.

**Interfaces:**
- Consumes: `artifacts/demo-seed/2026-10-14-emergent-update.sql` from Task 3.

- [ ] **Step 1 (owner, tunnel open): back up, count, apply**

```bash
cd backend && source /home/niki/Documents/workenv/pydev/bin/activate
IDS=$(python -c "import json; print(','.join(\"'%s'\" % e['id'] for e in json.load(open('scripts/demo_seed/emergency_departments.json'))['facilities']))")
./script.demo.local.sh query "select coalesce(json_agg(json_build_object('id', id, 'accepted_severity', accepted_severity)), '[]')::text from facilities where category = 'hospital'" | tail -n +2 > ../artifacts/demo-seed/2026-10-14-hospital-severity-backup-remote.json
./script.demo.local.sh query "select count(*) as hospitals, count(*) filter (where id = any(array[$IDS]::uuid[])) as listed_found from facilities where category = 'hospital'"
./script.demo.local.sh query "$(cat ../artifacts/demo-seed/2026-10-14-emergent-update.sql)"
```

Expected: `listed_found` equals the list length; then `type 'yes'`, `OK (<hospitals> rows affected)`.

- [ ] **Step 2: Check the remote database**

Run: `./script.demo.local.sh query "select name from facilities where 'emergent' = any(accepted_severity) order by 1"`
Expected: exactly the names in the list.

- [ ] **Step 3: Restart python-api so it reloads the facilities**

```bash
railway redeploy --service python-api --yes
```

Then wait until `railway deployment list --service python-api --json` shows the newest deployment `SUCCESS` on the same commit hash as before, and `curl -s https://medicoord.up.railway.app/health` answers `"status":"ok"`.

- [ ] **Step 4: Check the public facility list**

```bash
curl -s 'https://medicoord.up.railway.app/facilities?severity=emergent' | python -c "import json,sys; d=json.load(sys.stdin); print(len(d)); print(sorted(f['name'] for f in d))"
```

Expected: the list length and names match `emergency_departments.json` (it was 35 facilities, starting with Casey House Hospice, on 2026-10-14).

- [ ] **Step 5: One real chat turn at the chest-pain point**

```bash
G=$(python -c "import uuid; print(uuid.uuid4())")
S=$(curl -s -X POST https://medicoord.up.railway.app/chat/sessions -H 'Content-Type: application/json' -H "X-Guest-Id: $G" \
  -d '{"first_message": "Crushing chest pain for 20 minutes, sweating and short of breath"}' | python -c "import json,sys; print(json.load(sys.stdin)['id'])")
curl -s -X POST https://medicoord.up.railway.app/chat/message -H 'Content-Type: application/json' -H "X-Guest-Id: $G" \
  -d "{\"session_id\": \"$S\", \"content\": \"Crushing chest pain for 20 minutes, sweating and short of breath\", \"lat\": 43.70, \"lng\": -79.40}" \
  | python -c "import json,sys; t=json.load(sys.stdin).get('triage') or {}; print(t.get('severity'), (t.get('recommended_facility') or {}).get('name'))"
echo "guest to delete: $G"
```

Expected: `emergent <a name from the ER list>`. python-api has no internal-guest token, so this guest is not marked internal: the owner deletes it afterwards with `./script.demo.local.sh query "delete from guests where id = '<G>'"`.

### Task 5: Record and merge

**Files:**
- Modify: `CHANGELOG.md` (the open sprint's section)

- [ ] **Step 1: Changelog line**

Under the open sprint, a bullet: `Emergent cases go only to facilities with an emergency department (reviewed list in backend/scripts/demo_seed/emergency_departments.json, applied by the seed loader; demo database fixed 2026-10-14). Before: 16% of a Toronto grid sent emergent cases to rehabilitation, hospice, psychiatric or surgical sites.`

- [ ] **Step 2: Commit and open the PR to `preview` (after the owner's go)**

```bash
git add CHANGELOG.md
git commit -m "docs(changelog): record the emergent routing fix"
git push -u origin fix/emergent-er-only
```

The PR description lists any ER the review found that is not in our facility data. No AI attribution.
