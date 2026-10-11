# Demo Scaling (Sprint 22) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the demo API hold 1,000 to 2,000 chat turns in flight, refuse work past its limit
instead of queueing it, serve the map from memory, and choose and route a facility with one
Geoapify call per guest.

**Architecture:** Three independent changes on one branch. The map path keeps wait-time data and
the encoded facility list in process memory, versioned by the data. The chat turn awaits the LLM
on the event loop through the providers' async clients, reads history from Postgres, and passes
an admission check first. The recommendation is chosen through an in-memory cell index and a
load-aware score fed by Redis counters, and only the chosen facility is routed up front.

**Tech Stack:** Python / FastAPI / httpx / the Groq, OpenAI and Anthropic async SDK clients /
redis-py / psycopg_pool / prometheus_client / `h3` (new); React 18 / TypeScript / vitest.

**Spec:** `docs/superpowers/specs/2026-10-10-demo-scaling-design.md`. Read it with this plan.
This plan implements phases 1 to 3 (sections 5, 6 and 7) as tasks 1 to 16, and lists phases 0,
4, 5 and 6 as runbooks at the end.

## Global Constraints

- **Python environment:** `/home/niki/Documents/workenv/pydev/` is the only one. Before any
  Python command: `source /home/niki/Documents/workenv/pydev/bin/activate`. Never the system
  interpreter, never a new virtual environment, never `--user` or `--break-system-packages`.
- **Environment variables:** every test or run command goes through `doppler run --`.
- **Backend tests:** from `backend/`: `doppler run -- pytest <path> -q`. The whole suite is bare
  `doppler run -- pytest -q` from `backend/` (it also collects `backend/scripts/**/tests`).
- **Worker tests:** from `workers/`: `doppler run -- pytest tests -q`.
- **Web tests:** from `webapp/`: `doppler run -- npm run test`. Type check: `npx tsc -b`
  (not `tsc --noEmit`, which misses errors in this repo).
- **One new Python dependency:** `h3==4.*` (task 10). No other new dependency, Python or npm.
- **Severity values:** exactly `routine`, `moderate`, `urgent`, `emergent`. Never any synonym.
- **TypeScript:** strict, no `any`. **Python:** type hints on every function signature.
- **Contracts:** a changed request or response shape goes into `shared/types.ts` in the same
  task as the backend change.
- **Commits:** one per task, the one-line conventional message given in the task, files staged
  by name with a single `git add <file> <file> ...`. No body, no co-author line, no "generated
  with" line, no mention of any AI tool anywhere. Never push. Never commit on `main` or
  `preview`; the branch is `feat/demo-scaling`.
- **Secrets:** never print, log or commit a secret. `backend/.env.demo.staging` is never read,
  printed or staged.
- **Emergency line:** every busy or degraded state shown to a guest carries the text
  `If this is an emergency, call 911.`

## How to execute this plan

- Work through tasks 1 to 16 in order. Each task is test first: add the test, run it and see it
  fail for the stated reason, add the code, run it and see it pass, then run the whole suite of
  that side (backend or web), then commit.
- **Paste the code blocks as written.** Re-read each step from this file before doing it. Do not
  rewrite a block from memory, rename a function, or add tests of your own.
- Where a step gives **conversion rules** for existing tests, apply exactly those rules to
  exactly the listed files. If a test still fails for a reason the rules do not explain, stop.
- **Stop and report** instead of improvising when: a block does not apply because the file
  differs from what the step describes; a test fails for a reason other than the one stated; or
  a suite that was green before your change has a new failure you cannot trace to the task.
- **Three checkpoints**, marked `CHECKPOINT 1`, `2` and `3`. Stop at each one and wait for
  review. Do not start the next part before it is approved.

## Review Focus

Conditions the spec implies that are easy to get wrong. Each is pinned by a test in the task
named.

1. **A guest far from every facility, or a severity that few facilities accept.** The cell index
   must return exactly what the full scan returns, not an empty or shorter list, and a short
   list must be left to the scan, which is faster below about 1,000 facilities (task 10,
   `test_a_guest_far_from_every_facility_gets_the_same_answer_as_the_scan`,
   `test_a_severity_few_facilities_accept_is_still_found`).
2. **The worker is late, or has never run.** `wait:last_run` is absent, malformed or old:
   `max-age` must be the floor, never zero or negative, and the page must still load (task 2,
   `test_max_age_never_goes_below_the_floor`, `test_max_age_is_the_floor_without_a_last_run`).
3. **A turn refused at the admission limit.** Nothing is written, the guest's rate-limit
   allowance is untouched, and a retry does not store the message twice (task 8,
   `test_a_refused_turn_stores_nothing_and_does_not_count_against_the_rate_limit`).
4. **A conversation continues on another process or after a restart.** The agent must receive
   the earlier messages, and an unreadable history must refuse the turn instead of answering
   without context (task 7, `test_history_comes_from_the_store_and_reaches_the_agent`,
   `test_a_failed_history_read_is_503_and_nothing_reaches_the_llm`).
5. **An urgent or emergent case when the Geoapify budget is spent.** It is still routed; only
   routine and moderate get the estimated answer (task 14,
   `test_urgent_and_emergent_are_routed_even_when_the_budget_is_spent`).
6. **Redis is unreachable.** Load counters and their refresh fail quietly, the last wait-time
   copy is kept, and the chat still answers (task 2
   `test_an_empty_reload_keeps_the_previous_copy`, task 12
   `test_a_failed_write_is_swallowed`, `test_a_failed_refresh_keeps_the_previous_counts`).

## File Structure

New files:

| File | Responsibility |
|---|---|
| `backend/services/wait_cache.py` | Wait-time data in memory, background reload, data version, `max-age` |
| `backend/services/facility_bytes.py` | Encoded `/facilities` bodies, bounded, keyed by data version and filters |
| `backend/llm/limits.py` | Connection limits for the async SDK clients |
| `backend/llm/sync.py` | Run a coroutine from a script on one long-lived loop |
| `backend/services/admission.py` | Turns in flight, the limit, the retry delay |
| `backend/services/cell_index.py` | Facilities filed by H3 cell; candidate lookup |
| `backend/services/travel_time.py` | Travel-time estimate and the in-process travel-time cache |
| `backend/services/facility_load.py` | Redis load counters and their local copy |
| `backend/services/recommendation.py` | The load-aware choice among candidates |
| `backend/services/geoapify_limiter.py` | Token bucket in front of Geoapify |
| `backend/scripts/perf_baseline/bench_lookup.py` | Scan against index timing at 304, 10k, 100k facilities |
| `webapp/src/lib/waitAsOf.ts` | "Wait times as of HH:MM" text |

Modified files: `workers/scraper.py`, `backend/main.py`, `backend/config.py`,
`backend/metrics.py`, `backend/models.py`, `backend/requirements.txt`, `backend/llm/base.py`,
`backend/llm/groq_client.py`, `backend/llm/openai_client.py`, `backend/llm/anthropic_client.py`,
`backend/llm/instrumented.py`, `backend/llm/fallback.py`, `backend/services/llm_agent.py`,
`backend/services/chat.py`, `backend/services/guest_store.py`, `backend/services/proximity.py`,
`backend/services/routing.py`, `backend/routers/chat.py`, `backend/routers/routes.py`,
`backend/routers/demo.py`, `backend/scripts/symptom_eval/system_under_test.py`,
`backend/scripts/symptom_eval/patient_simulator.py`, `shared/types.ts`, `docs/API.md`,
`webapp/src/hooks/useFacilities.ts`, `webapp/src/hooks/useConversations.ts`,
`webapp/src/hooks/useTriageState.ts`, `webapp/src/lib/busy.ts`, `webapp/src/lib/config.ts`,
`webapp/src/lib/routesClient.ts`, `webapp/src/lib/triageRoutes.ts`, `webapp/src/App.tsx`,
`webapp/src/components/triage/TriageCard.tsx`,
`webapp/src/components/mobile/FacilityCardPanel.tsx`, and the test files named in each task.

Deleted: `backend/cache_chat.py`.

---

# Part 1: the map path (spec section 5)

### Task 1: The worker stamps its last successful run

**Files:**
- Modify: `workers/scraper.py` (the `REDIS_HASH_KEY` constant and `write_redis`)
- Test: `workers/tests/test_scraper.py` (class `TestSinks`)

**Interfaces:**
- Produces: the Redis string key `wait:last_run`, an ISO 8601 UTC timestamp, written in the same
  pipeline as the wait-time hash. Task 2 reads it.

- [ ] **Step 1: Add the failing tests**

In `workers/tests/test_scraper.py`, inside `class TestSinks`, directly after the method
`test_redis_is_one_pipeline_with_everything_including_the_predicted_flag`, add:

```python
    def test_redis_also_stamps_the_last_successful_run(self):
        client = MagicMock()
        scraper.write_redis(client, RECORDS)
        pipe = client.pipeline.return_value
        key, stamp = pipe.set.call_args.args
        assert key == "wait:last_run"
        assert __import__("datetime").datetime.fromisoformat(stamp).tzinfo is not None
        assert pipe.execute.call_count == 1

    def test_redis_does_not_stamp_a_run_without_records(self):
        client = MagicMock()
        assert scraper.write_redis(client, []) == 0
        client.pipeline.assert_not_called()
```

- [ ] **Step 2: Run them and see the first one fail**

Run (from `workers/`): `doppler run -- pytest tests/test_scraper.py -q -k "stamps or stamp_a_run"`
Expected: `test_redis_also_stamps_the_last_successful_run` FAILS with
`TypeError: cannot unpack non-iterable NoneType object` (the pipeline's `set` was never called).
`test_redis_does_not_stamp_a_run_without_records` passes already.

- [ ] **Step 3: Write the stamp**

In `workers/scraper.py`, directly below the line `REDIS_HASH_KEY = "wait_times:current"`, add:

```python
LAST_RUN_KEY = "wait:last_run"  # read by the API to version and age the wait-time data
```

In `write_redis`, replace the line `    pipe.execute()` with:

```python
    pipe.set(LAST_RUN_KEY, datetime.now(timezone.utc).isoformat())
    pipe.execute()
```

(`datetime` and `timezone` are already imported at the top of the file.)

- [ ] **Step 4: Run the worker tests**

Run (from `workers/`): `doppler run -- pytest tests -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add workers/scraper.py workers/tests/test_scraper.py
git commit -m "feat(worker): stamp the last successful wait-time run in redis"
```

---

### Task 2: Wait-time data held in memory

**Files:**
- Create: `backend/services/wait_cache.py`
- Test: `backend/tests/test_wait_cache.py`

**Interfaces:**
- Consumes: `services.wait_times.get_wait_map() -> dict[str, dict]` (never raises; returns `{}`
  when Redis and the database both fail) and `services.wait_times.redis_client`.
- Produces:
  - `WaitSnapshot(wait_map: dict[str, dict], version: str, last_run: datetime | None)`, frozen.
  - `current_wait() -> WaitSnapshot`: the copy in memory. Never blocks, never raises.
  - `refresh_once() -> WaitSnapshot`: blocking reload; keeps the previous copy on an empty load.
  - `next_delay(rng: Callable[[], float] = random.random) -> float`: seconds to the next reload.
  - `run_forever() -> None` (coroutine): the background loop.
  - `max_age_seconds(snapshot: WaitSnapshot, now: datetime | None = None) -> int`.
  - `reset_for_tests() -> None`.
  - Constants `LAST_RUN_KEY = "wait:last_run"`, `WORKER_INTERVAL_SECONDS = 900`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_wait_cache.py`:

```python file=backend/tests/test_wait_cache.py
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from services import wait_cache
from services.wait_cache import WaitSnapshot

INFO_A = {"a": {"wait_minutes": 10, "raw_wait": None, "predicted": False}}
INFO_B = {"b": {"wait_minutes": 20, "raw_wait": None, "predicted": False}}
T0 = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _clean():
    wait_cache.reset_for_tests()
    yield
    wait_cache.reset_for_tests()


def _refresh(wait_map: dict, last_run_raw: object) -> WaitSnapshot:
    with patch("services.wait_cache.get_wait_map", return_value=wait_map), \
         patch("services.wait_cache.redis_client") as redis_client:
        redis_client.get.return_value = last_run_raw
        return wait_cache.refresh_once()


def test_before_any_load_the_copy_is_empty() -> None:
    snapshot = wait_cache.current_wait()
    assert snapshot.wait_map == {} and snapshot.last_run is None


def test_a_refresh_replaces_the_copy_and_reads_the_last_run() -> None:
    _refresh(INFO_A, T0.isoformat())
    snapshot = wait_cache.current_wait()
    assert snapshot.wait_map == INFO_A and snapshot.last_run == T0


def test_the_version_changes_with_the_data_and_only_with_the_data() -> None:
    first = _refresh(INFO_A, T0.isoformat()).version
    assert _refresh(INFO_A, T0.isoformat()).version == first
    second = _refresh(INFO_B, T0.isoformat()).version
    assert second != first
    assert _refresh(INFO_B, (T0 + timedelta(minutes=15)).isoformat()).version != second


def test_an_empty_reload_keeps_the_previous_copy() -> None:
    before = _refresh(INFO_A, T0.isoformat())
    assert _refresh({}, None) is before
    assert wait_cache.current_wait().wait_map == INFO_A


def test_a_missing_or_malformed_last_run_keeps_the_previous_one() -> None:
    _refresh(INFO_A, T0.isoformat())
    assert _refresh(INFO_B, None).last_run == T0
    assert _refresh(INFO_A, "not a date").last_run == T0


def test_a_redis_error_on_the_last_run_does_not_fail_the_refresh() -> None:
    with patch("services.wait_cache.get_wait_map", return_value=INFO_A), \
         patch("services.wait_cache.redis_client") as redis_client:
        redis_client.get.side_effect = RuntimeError("redis down")
        snapshot = wait_cache.refresh_once()
    assert snapshot.wait_map == INFO_A and snapshot.last_run is None


def test_a_timestamp_without_a_zone_is_read_as_utc() -> None:
    assert _refresh(INFO_A, "2026-10-10T12:00:00").last_run == T0


def test_the_next_delay_is_the_ttl_plus_up_to_twenty_percent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WAIT_CACHE_TTL_SECONDS", "30")
    assert wait_cache.next_delay(lambda: 0.0) == 30
    assert wait_cache.next_delay(lambda: 1.0) == 36


def test_max_age_counts_down_to_the_next_run(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MAP_MIN_MAX_AGE_SECONDS", raising=False)
    snapshot = WaitSnapshot(INFO_A, "v", T0)
    assert wait_cache.max_age_seconds(snapshot, now=T0 + timedelta(minutes=5)) == 600


def test_max_age_never_goes_below_the_floor(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MAP_MIN_MAX_AGE_SECONDS", raising=False)
    snapshot = WaitSnapshot(INFO_A, "v", T0)
    assert wait_cache.max_age_seconds(snapshot, now=T0 + timedelta(minutes=14, seconds=50)) == 30
    assert wait_cache.max_age_seconds(snapshot, now=T0 + timedelta(hours=1)) == 30


def test_max_age_is_the_floor_without_a_last_run(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAP_MIN_MAX_AGE_SECONDS", "45")
    assert wait_cache.max_age_seconds(WaitSnapshot(INFO_A, "v", None), now=T0) == 45


def test_max_age_is_capped_at_the_worker_interval(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MAP_MIN_MAX_AGE_SECONDS", raising=False)
    snapshot = WaitSnapshot(INFO_A, "v", T0)
    assert wait_cache.max_age_seconds(snapshot, now=T0 - timedelta(minutes=5)) == 900
```

- [ ] **Step 2: Run them and see them fail**

Run (from `backend/`): `doppler run -- pytest tests/test_wait_cache.py -q`
Expected: collection error, `ImportError: cannot import name 'wait_cache' from 'services'`.

- [ ] **Step 3: Write the module**

Create `backend/services/wait_cache.py`:

```python file=backend/services/wait_cache.py
"""Wait-time data held in process memory.

A background task reloads it every WAIT_CACHE_TTL_SECONDS plus a random share of that, so
processes started together do not reload together. Request handlers read `current_wait()` and
never call Redis for wait data. A reload that comes back empty keeps the previous copy.
"""
import asyncio
import hashlib
import json
import logging
import random
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone

from starlette.concurrency import run_in_threadpool

from config import env_int
from services.wait_times import get_wait_map, redis_client

logger = logging.getLogger(__name__)

LAST_RUN_KEY = "wait:last_run"  # written by workers/scraper.py after each successful run
WORKER_INTERVAL_SECONDS = 900   # how often the worker runs
JITTER_FRACTION = 0.2


@dataclass(frozen=True)
class WaitSnapshot:
    """`wait_map` has the get_wait_map() shape. `version` changes when the data does."""

    wait_map: dict[str, dict]
    version: str
    last_run: datetime | None


def _version(wait_map: dict[str, dict], last_run: datetime | None) -> str:
    payload = json.dumps(
        [wait_map, last_run.isoformat() if last_run else None], sort_keys=True, default=str
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


_EMPTY = WaitSnapshot({}, _version({}, None), None)
_snapshot: WaitSnapshot = _EMPTY


def current_wait() -> WaitSnapshot:
    return _snapshot


def _read_last_run() -> datetime | None:
    try:
        raw = redis_client.get(LAST_RUN_KEY)
    except Exception as exc:
        logger.warning("wait_last_run_unavailable", extra={"error_type": type(exc).__name__})
        return None
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(str(raw))
    except ValueError:
        logger.warning("wait_last_run_malformed")
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def refresh_once() -> WaitSnapshot:
    """Blocking reload. An empty load is treated as a failed one: the previous copy stays."""
    global _snapshot
    wait_map = get_wait_map()
    if not wait_map and _snapshot.wait_map:
        logger.warning("wait_cache_reload_empty_keeping_previous")
        return _snapshot
    last_run = _read_last_run() or _snapshot.last_run
    _snapshot = WaitSnapshot(wait_map, _version(wait_map, last_run), last_run)
    return _snapshot


def next_delay(rng: Callable[[], float] = random.random) -> float:
    ttl = env_int("WAIT_CACHE_TTL_SECONDS", 30, minimum=1, maximum=WORKER_INTERVAL_SECONDS)
    return ttl * (1 + JITTER_FRACTION * rng())


async def run_forever() -> None:
    """The background reload. Started once by the app's lifespan and cancelled at shutdown."""
    while True:
        await asyncio.sleep(next_delay())
        try:
            await run_in_threadpool(refresh_once)
        except Exception as exc:
            logger.warning("wait_cache_reload_failed", extra={"error_type": type(exc).__name__})


def max_age_seconds(snapshot: WaitSnapshot, now: datetime | None = None) -> int:
    """Seconds a browser may reuse the map data: until the worker's next run, never below the
    floor (the worker can be late) and never above the worker's interval (clocks can differ)."""
    floor = env_int("MAP_MIN_MAX_AGE_SECONDS", 30, minimum=1, maximum=WORKER_INTERVAL_SECONDS)
    if snapshot.last_run is None:
        return floor
    now = now or datetime.now(timezone.utc)
    remaining = WORKER_INTERVAL_SECONDS - int((now - snapshot.last_run).total_seconds())
    return max(floor, min(remaining, WORKER_INTERVAL_SECONDS))


def reset_for_tests() -> None:
    global _snapshot
    _snapshot = _EMPTY
```

- [ ] **Step 4: Run the tests**

Run (from `backend/`): `doppler run -- pytest tests/test_wait_cache.py -q`
Expected: 12 passed.

- [ ] **Step 5: Commit**

```bash
git add backend/services/wait_cache.py backend/tests/test_wait_cache.py
git commit -m "feat(api): keep wait-time data in memory with a background reload"
```

---

### Task 3: `/facilities` encodes once per data version and serves bytes

**Files:**
- Create: `backend/services/facility_bytes.py`
- Modify: `backend/main.py` (imports, `lifespan`, the CORS middleware, `facilities`,
  `facilities_nearby`)
- Test: `backend/tests/test_facility_bytes.py` (new), `backend/tests/test_facilities_routes.py`
  (replaced)

**Interfaces:**
- Consumes: `current_wait()`, `max_age_seconds()`, `refresh_once()`, `run_forever()` from task 2;
  `cache.get_cached_facilities() -> tuple[list[dict] | None, str | None]`.
- Produces:
  - `facility_bytes.etag_for(key: tuple) -> str` (quoted), `encode(data: list[dict]) -> bytes`,
    `get(key) -> bytes | None`, `put(key, body: bytes) -> None`, `clear() -> None`,
    `MAX_ENTRIES = 64`.
  - `GET /facilities` answers with headers `ETag`, `Cache-Control: max-age=N` and, when the
    worker's last run is known, `X-Wait-As-Of`. A matching `If-None-Match` gets `304`.
  - `main.py` no longer imports `get_wait_map` or `get_wait_minutes_map`; handlers read
    `main.current_wait`.

- [ ] **Step 1: Write the failing tests for the bytes cache**

Create `backend/tests/test_facility_bytes.py`:

```python file=backend/tests/test_facility_bytes.py
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
```

- [ ] **Step 2: Run them and see them fail**

Run (from `backend/`): `doppler run -- pytest tests/test_facility_bytes.py -q`
Expected: collection error, `ImportError: cannot import name 'facility_bytes' from 'services'`.

- [ ] **Step 3: Write the bytes cache**

Create `backend/services/facility_bytes.py`:

```python file=backend/services/facility_bytes.py
"""The GET /facilities response body, encoded once per data version and filter set.

The key carries everything the body depends on: the facility list version, the wait-data
version and the three filters. The ETag is derived from the key, so answering a conditional
request needs neither the body nor a hash of it.
"""
import hashlib
import json
from collections import OrderedDict
from typing import Any

MAX_ENTRIES = 64  # `max_wait_minutes` is free-form: the cache must not grow with it

Key = tuple[Any, ...]

_entries: OrderedDict[Key, bytes] = OrderedDict()


def etag_for(key: Key) -> str:
    return '"' + hashlib.sha256(repr(key).encode()).hexdigest()[:32] + '"'


def encode(data: list[dict]) -> bytes:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")


def get(key: Key) -> bytes | None:
    body = _entries.get(key)
    if body is not None:
        _entries.move_to_end(key)
    return body


def put(key: Key, body: bytes) -> None:
    _entries[key] = body
    _entries.move_to_end(key)
    while len(_entries) > MAX_ENTRIES:
        _entries.popitem(last=False)


def clear() -> None:
    _entries.clear()
```

- [ ] **Step 4: Run the bytes cache tests**

Run (from `backend/`): `doppler run -- pytest tests/test_facility_bytes.py -q`
Expected: 4 passed.

- [ ] **Step 5: Replace the route tests**

Replace the whole content of `backend/tests/test_facilities_routes.py` with:

```python
"""
Unit tests for the /facilities and /facilities/nearby route handlers.
Called directly as plain async functions (bypassing the ASGI stack and
app lifespan) — only the filtering and caching logic under test needs exercising.
"""

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

import main
from services import facility_bytes
from services.wait_cache import WaitSnapshot

LAST_RUN = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)
TWO_HOSPITALS = [
    {"id": "a", "category": "hospital", "accepted_severity": ["urgent"]},
    {"id": "b", "category": "hospital", "accepted_severity": ["urgent"]},
]


def _info(**minutes: int) -> dict:
    """{'a': 10} -> the get_wait_map() shape."""
    return {fid: {"wait_minutes": m, "raw_wait": None, "predicted": False} for fid, m in minutes.items()}


def _snap(wait_map: dict, version: str = "w1", last_run: datetime | None = None) -> WaitSnapshot:
    return WaitSnapshot(wait_map, version, last_run)


def _request(**headers: str):
    return type("FakeRequest", (), {"headers": headers})()


@pytest.fixture(autouse=True)
def _empty_bytes_cache():
    facility_bytes.clear()
    yield
    facility_bytes.clear()


class TestFacilitiesRoute:
    def test_max_wait_minutes_filters_results(self):
        with patch("main.get_cached_facilities", return_value=(TWO_HOSPITALS, '"f1"')), \
             patch("main.current_wait", return_value=_snap(_info(a=10, b=60))):
            response = asyncio.run(main.facilities(_request(), max_wait_minutes=30))

        assert [r["id"] for r in json.loads(response.body)] == ["a"]

    def test_no_max_wait_minutes_returns_all(self):
        with patch("main.get_cached_facilities", return_value=(TWO_HOSPITALS, '"f1"')), \
             patch("main.current_wait", return_value=_snap(_info(a=10, b=60))):
            response = asyncio.run(main.facilities(_request()))

        assert len(json.loads(response.body)) == 2

    def test_facilities_treats_empty_cached_list_as_not_warm(self):
        """I-6 regression guard: an empty list (not None) from a lifespan warm-up
        that ran before the database had any operational rows must not be served
        forever — main.py's `if not cached_data` (not `is None`) re-queries and
        re-warms on the next request once real data exists."""
        fake_fresh_data = [
            {"id": "a", "category": "hospital", "accepted_severity": ["urgent"]},
        ]
        with patch("main.get_cached_facilities", return_value=([], "etag-empty")), \
             patch("main.get_all_facilities", return_value=fake_fresh_data), \
             patch("main.set_cached_facilities", return_value='"f-fresh"') as mock_set, \
             patch("main.current_wait", return_value=_snap(_info(a=10))):
            response = asyncio.run(main.facilities(_request()))

        assert [r["id"] for r in json.loads(response.body)] == ["a"]
        mock_set.assert_called_once_with(fake_fresh_data)

    def test_facilities_carry_raw_wait_and_predicted(self):
        fake_data = [{"id": "a", "category": "hospital", "accepted_severity": ["urgent"]}]
        wait = {"a": {"wait_minutes": None, "raw_wait": "45m–2h", "predicted": True}}
        with patch("main.get_cached_facilities", return_value=(fake_data, '"f1"')), \
             patch("main.current_wait", return_value=_snap(wait)):
            response = asyncio.run(main.facilities(_request(), max_wait_minutes=30))
        assert json.loads(response.body) == [
            {"id": "a", "category": "hospital", "accepted_severity": ["urgent"],
             "wait_minutes": None, "raw_wait": "45m–2h", "predicted": True}]


class TestFacilitiesCaching:
    def test_the_list_is_encoded_once_per_data_version(self):
        with patch("main.get_cached_facilities", return_value=(TWO_HOSPITALS, '"f1"')), \
             patch("main.current_wait", return_value=_snap(_info(a=10))), \
             patch.object(facility_bytes, "encode", wraps=facility_bytes.encode) as encode:
            first = asyncio.run(main.facilities(_request()))
            second = asyncio.run(main.facilities(_request()))

        assert encode.call_count == 1
        assert first.body == second.body and first.headers["ETag"] == second.headers["ETag"]

    def test_a_matching_if_none_match_is_304_without_encoding(self):
        with patch("main.get_cached_facilities", return_value=(TWO_HOSPITALS, '"f1"')), \
             patch("main.current_wait", return_value=_snap(_info(a=10))):
            first = asyncio.run(main.facilities(_request()))
            with patch.object(facility_bytes, "encode") as encode:
                second = asyncio.run(main.facilities(_request(**{"If-None-Match": first.headers["ETag"]})))

        assert second.status_code == 304 and second.body == b""
        assert second.headers["ETag"] == first.headers["ETag"]
        encode.assert_not_called()

    def test_new_wait_data_gives_a_new_etag_and_a_new_body(self):
        with patch("main.get_cached_facilities", return_value=(TWO_HOSPITALS, '"f1"')):
            with patch("main.current_wait", return_value=_snap(_info(a=10), version="w1")):
                before = asyncio.run(main.facilities(_request()))
            with patch("main.current_wait", return_value=_snap(_info(a=45), version="w2")):
                after = asyncio.run(main.facilities(_request()))

        assert before.headers["ETag"] != after.headers["ETag"]
        assert json.loads(after.body)[0]["wait_minutes"] == 45

    def test_each_filter_set_has_its_own_etag(self):
        with patch("main.get_cached_facilities", return_value=(TWO_HOSPITALS, '"f1"')), \
             patch("main.current_wait", return_value=_snap(_info(a=10, b=60))):
            everything = asyncio.run(main.facilities(_request()))
            short_waits = asyncio.run(main.facilities(_request(), max_wait_minutes=30))

        assert everything.headers["ETag"] != short_waits.headers["ETag"]
        assert len(json.loads(everything.body)) == 2 and len(json.loads(short_waits.body)) == 1

    def test_the_browser_may_reuse_the_answer_until_the_next_worker_run(self):
        with patch("main.get_cached_facilities", return_value=(TWO_HOSPITALS, '"f1"')), \
             patch("main.current_wait", return_value=_snap(_info(a=10), last_run=LAST_RUN)), \
             patch("main.max_age_seconds", return_value=600):
            response = asyncio.run(main.facilities(_request()))

        assert response.headers["Cache-Control"] == "max-age=600"
        assert response.headers["X-Wait-As-Of"] == LAST_RUN.isoformat()

    def test_without_a_known_run_there_is_no_as_of_header(self):
        with patch("main.get_cached_facilities", return_value=(TWO_HOSPITALS, '"f1"')), \
             patch("main.current_wait", return_value=_snap(_info(a=10))):
            response = asyncio.run(main.facilities(_request()))

        assert "X-Wait-As-Of" not in response.headers
        assert response.headers["Cache-Control"].startswith("max-age=")

    def test_no_request_reads_wait_times_from_redis(self):
        with patch("main.get_cached_facilities", return_value=(TWO_HOSPITALS, '"f1"')), \
             patch("main.current_wait", return_value=_snap(_info(a=10))), \
             patch("main.supabase_rpc", return_value=[]), \
             patch("services.wait_cache.get_wait_map") as load:
            asyncio.run(main.facilities(_request()))
            asyncio.run(main.facilities_nearby(lat=43.6, lng=-79.4))

        load.assert_not_called()


class TestFacilitiesNearbyRoute:
    def test_max_wait_minutes_filters_results(self):
        fake_rows = [
            {"facility_id": "a", "distance_m": 100},
            {"facility_id": "b", "distance_m": 200},
        ]
        with patch("main.supabase_rpc", return_value=fake_rows), \
             patch("main.current_wait", return_value=_snap(_info(a=10, b=999))):
            result = asyncio.run(main.facilities_nearby(lat=43.6, lng=-79.4, max_wait_minutes=30))

        assert [r["facility_id"] for r in result] == ["a"]

    def test_rpc_failure_raises_500(self):
        from fastapi import HTTPException

        with patch("main.supabase_rpc", side_effect=Exception("rpc down")):
            with pytest.raises(HTTPException) as exc_info:
                asyncio.run(main.facilities_nearby(lat=43.6, lng=-79.4))
        assert exc_info.value.status_code == 500


from fastapi.testclient import TestClient


class TestFacilitiesNearbyAsgiStack:
    def test_valid_rpc_response_passes_response_model_validation(self):
        fake_rows = [{
            "facility_id": "11111111-1111-1111-1111-111111111111",
            "facility_name": "Test Hospital",
            "category": "hospital",
            "address": "123 Main St",
            "phone": None,
            "is_operational": True,
            "distance_m": 100,
            "eta_walk_min": 20,
            "eta_transit_min": 10,
            "eta_drive_min": 5,
        }]
        with patch("main.supabase_rpc", return_value=fake_rows), \
             patch("main.current_wait", return_value=_snap({})), \
             patch("main.wait_cache.refresh_once"):
            with TestClient(main.app) as client:
                resp = client.get("/facilities/nearby", params={"lat": 43.6, "lng": -79.4})

        assert resp.status_code == 200
        body = resp.json()
        assert body[0]["facility_id"] == "11111111-1111-1111-1111-111111111111"
        assert body[0]["wait_minutes"] is None


class TestFacilitiesRouteUsesThreadpool:
    async def _run_inline(self, fn, *args, **kwargs):
        return fn(*args, **kwargs)

    def test_nearby_rpc_call_is_offloaded_to_threadpool(self):
        fake_rows = [{"facility_id": "a", "distance_m": 100}]
        with patch("main.supabase_rpc", return_value=fake_rows) as mock_rpc, \
             patch("main.current_wait", return_value=_snap(_info(a=10))), \
             patch("main.run_in_threadpool", side_effect=self._run_inline) as mock_threadpool:
            asyncio.run(main.facilities_nearby(lat=43.6, lng=-79.4))

        mock_threadpool.assert_any_call(
            mock_rpc,
            "nearby_facilities",
            {
                "user_lat": 43.6, "user_lng": -79.4, "radius_m": 5000,
                "facility_types": None, "result_limit": 50,
            },
        )


class TestFacilitiesNearbyDemoBranch:
    ROW = {
        "facility_id": "a", "facility_name": "A", "category": "hospital", "address": "1 Main St",
        "phone": None, "is_operational": True, "distance_m": 800,
        "eta_walk_min": 10, "eta_transit_min": 2, "eta_drive_min": 1,
    }

    def test_demo_mode_reads_the_cache_and_never_calls_supabase(self, monkeypatch):
        monkeypatch.setenv("DEMO_MODE", "true")
        with patch("main.find_facilities_within", return_value=[self.ROW]) as within, \
             patch("main.supabase_rpc") as rpc, \
             patch("main.current_wait", return_value=_snap(_info(a=25))):
            result = asyncio.run(main.facilities_nearby(lat=43.6, lng=-79.4, radius_m=10000, category="hospital"))

        within.assert_called_once_with(43.6, -79.4, 10000, "hospital")
        rpc.assert_not_called()
        assert result == [{**self.ROW, "wait_minutes": 25}]

    def test_demo_mode_applies_the_wait_filter(self, monkeypatch):
        monkeypatch.setenv("DEMO_MODE", "true")
        with patch("main.find_facilities_within", return_value=[self.ROW]), \
             patch("main.current_wait", return_value=_snap(_info(a=90))):
            assert asyncio.run(main.facilities_nearby(lat=43.6, lng=-79.4, max_wait_minutes=30)) == []

    def test_demo_mode_with_an_empty_cache_is_503(self, monkeypatch):
        from fastapi import HTTPException

        monkeypatch.setenv("DEMO_MODE", "true")
        with patch("main.find_facilities_within", return_value=None):
            with pytest.raises(HTTPException) as exc_info:
                asyncio.run(main.facilities_nearby(lat=43.6, lng=-79.4))
        assert exc_info.value.status_code == 503

    def test_without_demo_mode_the_supabase_function_is_still_called(self, monkeypatch):
        monkeypatch.delenv("DEMO_MODE", raising=False)
        with patch("main.find_facilities_within") as within, \
             patch("main.supabase_rpc", return_value=[]) as rpc, \
             patch("main.current_wait", return_value=_snap({})):
            assert asyncio.run(main.facilities_nearby(lat=43.6, lng=-79.4)) == []
        within.assert_not_called()
        rpc.assert_called_once()
```

- [ ] **Step 6: Run the route tests and see them fail**

Run (from `backend/`): `doppler run -- pytest tests/test_facilities_routes.py -q`
Expected: every test fails with `AttributeError: <module 'main'> does not have the attribute 'current_wait'`.

- [ ] **Step 7: Change `backend/main.py`**

(a) Replace the import block at the top of the file (the lines from `import logging` down to
`from routers.routes import router as routes_router`) with:

```python
import asyncio
import logging
import os
import demo_db
from config import demo_mode
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from starlette.concurrency import run_in_threadpool
from services import facility_bytes, wait_cache
from services.facilities import get_all_facilities, apply_wait_filter, annotate_wait_details
from services.wait_cache import current_wait, max_age_seconds
from services.proximity import find_facilities_within
from db import supabase_rpc
from models import NearbyFacilityResult
from middleware.auth import AuthMiddleware, get_current_user
from cache import get_cached_facilities, set_cached_facilities
from graph.factory import close_graph_provider, get_graph_provider
from observability import init_observability, verify_metrics_token, RequestIDMiddleware, _registry
from routers.chat import router as chat_router
from routers.notifications import router as notifications_router
from routers.demo import router as demo_router
from routers.routes import router as routes_router
```

(b) Replace the whole `lifespan` function with:

```python
@asynccontextmanager
async def lifespan(_app: FastAPI):
    if demo_mode():
        try:
            demo_db.open_pool()
        except Exception as exc:
            logger.warning("demo_db_pool_open_failed", extra={"error_type": type(exc).__name__})
    try:
        data = get_all_facilities()
        set_cached_facilities(data)
        logger.info("cache_warm", extra={"facility_count": len(data)})
    except Exception as exc:
        logger.warning("cache_warm_failed", extra={"error_type": type(exc).__name__})
    try:
        await run_in_threadpool(wait_cache.refresh_once)
    except Exception as exc:
        logger.warning("wait_cache_warm_failed", extra={"error_type": type(exc).__name__})
    background_tasks = [asyncio.create_task(wait_cache.run_forever())]
    yield
    for task in background_tasks:
        task.cancel()
    close_graph_provider()
    demo_db.close_pool()
```

(c) In the `app.add_middleware(CORSMiddleware, ...)` call, add one argument after the
`allow_headers=[...]` line:

```python
    expose_headers=["ETag", "X-Wait-As-Of"],
```

(d) Replace the whole `facilities` handler (from `@app.get("/facilities")` down to the end of
its `return JSONResponse(...)` statement) with:

```python
@app.get("/facilities")
async def facilities(
    request: Request,
    category: str | None = None,
    severity: str | None = None,
    max_wait_minutes: int | None = None,
) -> Response:
    cached_data, facilities_etag = get_cached_facilities()

    # `cache.py` has no TTL/invalidation. `cached_data is None` alone isn't enough:
    # if the lifespan warm-up ran before the database had rows (or before they were
    # marked is_operational), it caches `[]` — not None — and every request since
    # would serve that empty snapshot forever. Treat an empty cache as not-yet-warm
    # too, so it self-heals on the next request once real data exists.
    if not cached_data:
        raw = get_all_facilities(category=None, severity=None)
        facilities_etag = set_cached_facilities(raw)
        cached_data = raw

    wait = current_wait()
    # Everything the body depends on. The ETag comes from this key, so a conditional request
    # is answered without building, encoding or hashing the list.
    key = (facilities_etag, wait.version, category, severity, max_wait_minutes)
    etag = facility_bytes.etag_for(key)
    headers = {"ETag": etag, "Cache-Control": f"max-age={max_age_seconds(wait)}"}
    if wait.last_run is not None:
        headers["X-Wait-As-Of"] = wait.last_run.isoformat()

    if request.headers.get("If-None-Match", "") == etag:
        return Response(status_code=304, headers=headers)

    body = facility_bytes.get(key)
    if body is None:
        data: list[dict] = cached_data
        if category:
            data = [r for r in data if r["category"] == category]
        if severity:
            data = [r for r in data if severity in r.get("accepted_severity", [])]
        wait_minutes = {fid: info.get("wait_minutes") for fid, info in wait.wait_map.items()}
        data = apply_wait_filter(data, "id", max_wait_minutes, wait_minutes)
        data = annotate_wait_details(data, "id", wait.wait_map)
        body = facility_bytes.encode(data)
        facility_bytes.put(key, body)

    return Response(content=body, media_type="application/json", headers=headers)
```

(e) In `facilities_nearby`, replace the last two lines of the function

```python
    wait_map = await run_in_threadpool(get_wait_minutes_map)
    return apply_wait_filter(data, "facility_id", max_wait_minutes, wait_map)
```

with:

```python
    wait_minutes = {fid: info.get("wait_minutes") for fid, info in current_wait().wait_map.items()}
    return apply_wait_filter(data, "facility_id", max_wait_minutes, wait_minutes)
```

- [ ] **Step 8: Run the tests**

Run (from `backend/`): `doppler run -- pytest tests/test_facilities_routes.py tests/test_facility_bytes.py -q`
Expected: all pass.

Run the whole backend suite: `doppler run -- pytest -q`
Expected: no new failure. (`tests/test_wait_times.py` still passes: `get_wait_map` is unchanged.)

- [ ] **Step 9: Commit**

```bash
git add backend/services/facility_bytes.py backend/main.py backend/tests/test_facility_bytes.py backend/tests/test_facilities_routes.py
git commit -m "feat(api): serve the facility list as bytes encoded once per data version"
```

---

### Task 4: The web app shows when the wait times were read

**Files:**
- Create: `webapp/src/lib/waitAsOf.ts`
- Modify: `webapp/src/hooks/useFacilities.ts`, `webapp/src/App.tsx`
- Test: `webapp/src/lib/waitAsOf.test.ts`

**Interfaces:**
- Consumes: the `X-Wait-As-Of` response header from task 3.
- Produces: `formatWaitAsOf(iso: string | null, timeZone?: string): string | null`;
  `useFacilities()` also returns `waitAsOf: string | null`.

- [ ] **Step 1: Write the failing test**

Create `webapp/src/lib/waitAsOf.test.ts`:

```ts
import { describe, expect, it } from "vitest"
import { formatWaitAsOf } from "./waitAsOf"

describe("formatWaitAsOf", () => {
  it("shows the hour and minute of the worker's last run", () => {
    expect(formatWaitAsOf("2026-10-10T12:05:00+00:00", "UTC")).toBe("Wait times as of 12:05")
  })

  it("uses a 24 hour clock that starts at 00", () => {
    expect(formatWaitAsOf("2026-10-10T00:07:00+00:00", "UTC")).toBe("Wait times as of 00:07")
  })

  it("converts to the given time zone", () => {
    expect(formatWaitAsOf("2026-10-10T12:05:00+00:00", "America/Toronto")).toBe("Wait times as of 08:05")
  })

  it("is null without a header or with an unreadable one", () => {
    expect(formatWaitAsOf(null)).toBeNull()
    expect(formatWaitAsOf("")).toBeNull()
    expect(formatWaitAsOf("not a date")).toBeNull()
  })
})
```

- [ ] **Step 2: Run it and see it fail**

Run (from `webapp/`): `doppler run -- npm run test -- src/lib/waitAsOf.test.ts`
Expected: FAIL, `Failed to resolve import "./waitAsOf"`.

- [ ] **Step 3: Write the formatter**

Create `webapp/src/lib/waitAsOf.ts`:

```ts
/** "Wait times as of 14:05" from the X-Wait-As-Of header, or null when there is nothing to show. */
export function formatWaitAsOf(iso: string | null, timeZone?: string): string | null {
  if (!iso) return null
  const at = new Date(iso)
  if (Number.isNaN(at.getTime())) return null
  const clock = new Intl.DateTimeFormat("en-CA", {
    hour: "2-digit", minute: "2-digit", hourCycle: "h23", timeZone,
  }).format(at)
  return `Wait times as of ${clock}`
}
```

- [ ] **Step 4: Run the test**

Run (from `webapp/`): `doppler run -- npm run test -- src/lib/waitAsOf.test.ts`
Expected: 4 passed.

- [ ] **Step 5: Return the header from the hook**

In `webapp/src/hooks/useFacilities.ts`:

(a) Replace the `UseFacilitiesResult` interface with:

```ts
interface UseFacilitiesResult {
  facilities: Facility[]
  loading: boolean
  error: string | null
  /** ISO time of the worker's last successful run, from the X-Wait-As-Of header. */
  waitAsOf: string | null
}
```

(b) Directly below the line `const [error, setError]           = useState<string | null>(null)` add:

```ts
  const [waitAsOf, setWaitAsOf]     = useState<string | null>(null)
```

(c) Replace the block

```ts
        if (!cancelled) {
          setFacilities(data)
          setError(null)
        }
```

with:

```ts
        if (!cancelled) {
          setFacilities(data)
          setWaitAsOf(res.headers.get("X-Wait-As-Of"))
          setError(null)
        }
```

(d) Replace `return { facilities, loading, error }` with `return { facilities, loading, error, waitAsOf }`.

- [ ] **Step 6: Show it**

In `webapp/src/App.tsx`:

(a) Add this import next to the other `./lib/...` or hook imports at the top of the file:

```ts
import { formatWaitAsOf } from "./lib/waitAsOf"
```

(b) In `AppInner`, replace

```ts
  const { facilities, loading: facilitiesLoading } = useFacilities()
```

with:

```ts
  const { facilities, loading: facilitiesLoading, waitAsOf } = useFacilities()
  const waitAsOfLabel = formatWaitAsOf(waitAsOf)
```

(c) In the JSX returned by `AppInner`, directly below the line `<Notification />`, add:

```tsx
      {waitAsOfLabel && (
        <div
          data-testid="wait-as-of"
          className="fixed left-2 bottom-1 z-[400] text-[10px] font-mono pointer-events-none"
          style={{ color: "#7AA0B0" }}
        >
          {waitAsOfLabel}
        </div>
      )}
```

- [ ] **Step 7: Check types and tests**

Run (from `webapp/`): `npx tsc -b` — expected: no error.
Run (from `webapp/`): `doppler run -- npm run test` — expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add webapp/src/lib/waitAsOf.ts webapp/src/lib/waitAsOf.test.ts webapp/src/hooks/useFacilities.ts webapp/src/App.tsx
git commit -m "feat(web): show when the wait times were last read"
```

---

## CHECKPOINT 1

Stop here. Report: the four commit hashes, the output of the whole backend suite, the worker
suite and the web suite, and anything that did not apply as written. Wait for review.

---

# Part 2: the chat turn (spec section 6)

### Task 5: The LLM clients become async

**Files:**
- Create: `backend/llm/limits.py`, `backend/llm/sync.py`
- Modify: `backend/llm/base.py`, `backend/llm/groq_client.py`, `backend/llm/openai_client.py`,
  `backend/llm/anthropic_client.py`, `backend/llm/instrumented.py`, `backend/llm/fallback.py`
- Test: `backend/tests/llm/test_async_clients.py` (new); conversions in
  `backend/tests/llm/test_groq_client.py`, `test_openai_client.py`, `test_client_factory.py`,
  `test_fallback.py`, `test_instrumented.py`

**Interfaces:**
- Produces:
  - `BaseLLMClient.chat(...)` is now `async def`, same parameters, same `LLMResponse`.
  - `llm.limits.connection_limits() -> httpx.Limits` from `LLM_MAX_CONNECTIONS` (default 2000).
  - `llm.sync.run_sync(coroutine) -> T`: for scripts only, never for the API.
- After this task the agent (`services/llm_agent.py`) is broken until task 6: it still calls
  `chat` without `await`. Tasks 5 and 6 are committed separately but checked together at step 8
  of task 6. Do not stop between them.

Why explicit limits: the Groq SDK's own async client allows 100 connections by default, the
OpenAI and Anthropic ones 1,000. Left alone, that would cap turns in flight below the target.

- [ ] **Step 1: Write the new failing tests**

Create `backend/tests/llm/test_async_clients.py`:

```python file=backend/tests/llm/test_async_clients.py
import asyncio
import inspect
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from unittest.mock import patch

import httpx
import pytest

from llm.limits import connection_limits
from llm.sync import run_sync


@pytest.fixture(autouse=True)
def _keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "g")
    monkeypatch.setenv("OPENAI_API_KEY", "o")
    monkeypatch.setenv("OPENAI_MODEL", "test-model")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "a")
    monkeypatch.delenv("LLM_MAX_CONNECTIONS", raising=False)


def test_every_client_chat_is_a_coroutine_function() -> None:
    from llm.anthropic_client import AnthropicClient
    from llm.base import BaseLLMClient
    from llm.fallback import FallbackLLMClient
    from llm.groq_client import GroqClient
    from llm.instrumented import InstrumentedLLMClient
    from llm.openai_client import OpenAIClient

    for cls in (BaseLLMClient, GroqClient, OpenAIClient, AnthropicClient, FallbackLLMClient, InstrumentedLLMClient):
        assert inspect.iscoroutinefunction(cls.chat), cls.__name__


def test_connection_limits_default_to_2000() -> None:
    limits = connection_limits()
    assert limits.max_connections == 2000 and limits.max_keepalive_connections == 2000


def test_connection_limits_come_from_the_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_MAX_CONNECTIONS", "1234")
    assert connection_limits().max_connections == 1234


def test_a_bad_connection_setting_falls_back_to_the_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_MAX_CONNECTIONS", "plenty")
    assert connection_limits().max_connections == 2000


@pytest.mark.parametrize("module, sdk_name, client_name", [
    ("llm.groq_client", "AsyncGroq", "GroqClient"),
    ("llm.openai_client", "AsyncOpenAI", "OpenAIClient"),
])
def test_each_sdk_client_is_async_and_given_an_explicit_http_client(module: str, sdk_name: str, client_name: str) -> None:
    import importlib

    with patch(f"{module}.{sdk_name}") as sdk:
        getattr(importlib.import_module(module), client_name)()
    assert isinstance(sdk.call_args.kwargs["http_client"], httpx.AsyncClient)


def test_the_anthropic_client_is_async_and_given_an_explicit_http_client() -> None:
    from llm.anthropic_client import AnthropicClient

    with patch("llm.anthropic_client.anthropic.AsyncAnthropic") as sdk:
        AnthropicClient()
    assert isinstance(sdk.call_args.kwargs["http_client"], httpx.AsyncClient)


def test_run_sync_returns_the_result_and_reuses_one_loop() -> None:
    async def loop_id() -> int:
        return id(asyncio.get_running_loop())

    assert run_sync(loop_id()) == run_sync(loop_id())


def test_run_sync_lets_the_exception_through() -> None:
    async def boom() -> None:
        raise ValueError("boom")

    with pytest.raises(ValueError, match="boom"):
        run_sync(boom())
```

- [ ] **Step 2: Run them and see them fail**

Run (from `backend/`): `doppler run -- pytest tests/llm/test_async_clients.py -q`
Expected: collection error, `ModuleNotFoundError: No module named 'llm.limits'`.

- [ ] **Step 3: Add the two small modules**

Create `backend/llm/limits.py`:

```python file=backend/llm/limits.py
"""Connection limits for the providers' async HTTP clients.

Set explicitly because the SDK defaults are a hidden cap on LLM calls in flight: 100 for Groq,
1,000 for OpenAI and Anthropic.
"""
import httpx

from config import env_int


def connection_limits() -> httpx.Limits:
    connections = env_int("LLM_MAX_CONNECTIONS", 2000, minimum=1, maximum=20000)
    return httpx.Limits(max_connections=connections, max_keepalive_connections=connections)
```

Create `backend/llm/sync.py`:

```python file=backend/llm/sync.py
"""Runs a coroutine from synchronous code. For scripts and the evaluation harness, never the API.

One event loop is kept for the life of the process: the providers' async HTTP clients are bound
to the loop they first ran on, so a new loop per call (asyncio.run) would break their
connections on the second call.
"""
import asyncio
from collections.abc import Coroutine
from typing import Any, TypeVar

T = TypeVar("T")

_loop: asyncio.AbstractEventLoop | None = None


def run_sync(coroutine: Coroutine[Any, Any, T]) -> T:
    global _loop
    if _loop is None or _loop.is_closed():
        _loop = asyncio.new_event_loop()
    return _loop.run_until_complete(coroutine)
```

- [ ] **Step 4: Make the interface and the three providers async**

(a) `backend/llm/base.py`: in `class BaseLLMClient`, replace

```python
    @abstractmethod
    def chat(
```

with:

```python
    @abstractmethod
    async def chat(
```

(b) `backend/llm/groq_client.py`:

Replace the first four lines of the file

```python
import os
from groq import BadRequestError, Groq
from config import llm_timeout_seconds
from .base import BaseLLMClient, LLMMessage, LLMResponse, ToolDefinition
```

with:

```python
import os
from groq import AsyncGroq, BadRequestError, DefaultAsyncHttpxClient
from config import llm_timeout_seconds
from .base import BaseLLMClient, LLMMessage, LLMResponse, ToolDefinition
from .limits import connection_limits
```

Replace

```python
        options: dict = {"api_key": api_key, "timeout": llm_timeout_seconds()}
        if max_retries is not None:
            options["max_retries"] = max_retries
        self._client = Groq(**options)
```

with:

```python
        options: dict = {
            "api_key": api_key,
            "timeout": llm_timeout_seconds(),
            "http_client": DefaultAsyncHttpxClient(limits=connection_limits()),
        }
        if max_retries is not None:
            options["max_retries"] = max_retries
        self._client = AsyncGroq(**options)
```

Replace `    def chat(` with `    async def chat(`.

Replace both occurrences of

```python
resp = self._client.chat.completions.create(**kwargs)
```

with (keep each line's indentation):

```python
resp = await self._client.chat.completions.create(**kwargs)
```

(c) `backend/llm/openai_client.py`:

Replace `from openai import OpenAI` with `from openai import AsyncOpenAI, DefaultAsyncHttpxClient`.

Replace `from .base import BaseLLMClient, LLMMessage, LLMResponse, ToolDefinition` with:

```python
from .base import BaseLLMClient, LLMMessage, LLMResponse, ToolDefinition
from .limits import connection_limits
```

Replace

```python
        options: dict = {"api_key": api_key, "timeout": llm_timeout_seconds()}
        if max_retries is not None:
            options["max_retries"] = max_retries
        self._client = OpenAI(**options)
```

with:

```python
        options: dict = {
            "api_key": api_key,
            "timeout": llm_timeout_seconds(),
            "http_client": DefaultAsyncHttpxClient(limits=connection_limits()),
        }
        if max_retries is not None:
            options["max_retries"] = max_retries
        self._client = AsyncOpenAI(**options)
```

Replace `    def chat(` with `    async def chat(`.

Replace `        resp = self._client.chat.completions.create(**kwargs)` with
`        resp = await self._client.chat.completions.create(**kwargs)`.

(d) `backend/llm/anthropic_client.py`:

Replace `from .base import BaseLLMClient, LLMMessage, LLMResponse, ToolDefinition` with:

```python
from .base import BaseLLMClient, LLMMessage, LLMResponse, ToolDefinition
from .limits import connection_limits
```

Replace

```python
        options: dict = {"api_key": api_key, "timeout": llm_timeout_seconds()}
        if max_retries is not None:
            options["max_retries"] = max_retries
        self._client = anthropic.Anthropic(**options)
```

with:

```python
        options: dict = {
            "api_key": api_key,
            "timeout": llm_timeout_seconds(),
            "http_client": anthropic.DefaultAsyncHttpxClient(limits=connection_limits()),
        }
        if max_retries is not None:
            options["max_retries"] = max_retries
        self._client = anthropic.AsyncAnthropic(**options)
```

Replace `    def chat(` with `    async def chat(`.

Replace `        resp = self._client.messages.create(**kwargs)` with
`        resp = await self._client.messages.create(**kwargs)`.

- [ ] **Step 5: Make the two wrappers async**

(a) `backend/llm/instrumented.py`: replace `    def chat(` with `    async def chat(`, and replace

```python
                    response = self._inner.chat(
```

with:

```python
                    response = await self._inner.chat(
```

(b) `backend/llm/fallback.py`: replace `    def chat(` with `    async def chat(`, and replace

```python
                response = client.chat(
```

with:

```python
                response = await client.chat(
```

- [ ] **Step 6: Convert the existing client tests**

Apply these rules to `backend/tests/llm/test_groq_client.py`, `test_openai_client.py`,
`test_client_factory.py`, `test_fallback.py` and `test_instrumented.py`, and to nothing else.

| Rule | Change |
|---|---|
| R1 | Add `import asyncio` to the file's imports. Where R5 or R6 is used, add `AsyncMock` and `ANY` to its `from unittest.mock import ...` line. |
| R2 | Wrap every call of `.chat(` on one of our clients: `X.chat(...)` becomes `asyncio.run(X.chat(...))`. This covers calls on `GroqClient`, `OpenAIClient`, `AnthropicClient`, `FallbackLLMClient`, `InstrumentedLLMClient` and on the test fakes that subclass `BaseLLMClient`. It does not cover `sdk.return_value.chat.completions...`, which is the mocked SDK. |
| R3 | In the test fakes that subclass `BaseLLMClient` (`class _Fake` in `test_fallback.py` and in `test_instrumented.py`), `def chat(` becomes `async def chat(`. |
| R4 | SDK patch targets: `"llm.groq_client.Groq"` becomes `"llm.groq_client.AsyncGroq"`; `"llm.openai_client.OpenAI"` becomes `"llm.openai_client.AsyncOpenAI"`; `"llm.anthropic_client.anthropic.Anthropic"` becomes `"llm.anthropic_client.anthropic.AsyncAnthropic"`. |
| R5 | A mocked SDK `create` must be awaitable. In `test_openai_client.py`, `sdk.return_value.chat.completions.create.return_value = completion or _completion()` becomes `sdk.return_value.chat.completions.create = AsyncMock(return_value=completion or _completion())`. In `test_client_factory.py`, the two statements `create = _env["anthropic"].return_value.messages.create` and `create.return_value = MagicMock(...)` become `create = AsyncMock(return_value=MagicMock(...))` (same `MagicMock(...)` argument) followed by `_env["anthropic"].return_value.messages.create = create`. |
| R6 | Every expected dictionary compared with an SDK constructor's `call_args.kwargs` gains `"http_client": ANY`. For example `{"api_key": "g", "timeout": 9}` becomes `{"api_key": "g", "timeout": 9, "http_client": ANY}`. |

`test_groq_client.py` uses `patch.object(client._client.chat.completions, "create", side_effect=[...])`:
leave those lines as they are. `patch.object` on an async method produces an awaitable mock by
itself.

- [ ] **Step 7: Run the client tests**

Run (from `backend/`):
`doppler run -- pytest tests/llm/test_async_clients.py tests/llm/test_groq_client.py tests/llm/test_openai_client.py tests/llm/test_client_factory.py tests/llm/test_fallback.py tests/llm/test_instrumented.py -q`
Expected: all pass. A failure that says `coroutine ... was never awaited`, or
`object MagicMock can't be used in 'await' expression`, means one site of R2 or R5 was missed:
apply the rule there. Any other failure: stop and report.

Do not run the whole suite yet: the agent tests fail until task 6.

- [ ] **Step 8: Commit**

```bash
git add backend/llm/limits.py backend/llm/sync.py backend/llm/base.py backend/llm/groq_client.py backend/llm/openai_client.py backend/llm/anthropic_client.py backend/llm/instrumented.py backend/llm/fallback.py backend/tests/llm/test_async_clients.py backend/tests/llm/test_groq_client.py backend/tests/llm/test_openai_client.py backend/tests/llm/test_client_factory.py backend/tests/llm/test_fallback.py backend/tests/llm/test_instrumented.py
git commit -m "feat(llm): call the providers through their async clients with explicit connection limits"
```

---

### Task 6: The agent awaits the LLM and is built once per process

**Files:**
- Modify: `backend/services/llm_agent.py`,
  `backend/scripts/symptom_eval/system_under_test.py`,
  `backend/scripts/symptom_eval/patient_simulator.py`
- Test: `backend/tests/llm/test_agent_async.py` (new); conversions in
  `backend/tests/llm/test_triage_tools.py`, `backend/tests/llm/test_emergency_mismatch_logging.py`,
  `backend/scripts/symptom_eval/tests/test_system_under_test.py`,
  `backend/scripts/symptom_eval/tests/test_patient_simulator.py`

**Interfaces:**
- Consumes: `BaseLLMClient.chat` (async, task 5), `llm.sync.run_sync` (task 5).
- Produces:
  - `LLMAgent.respond(...)` is now `async def`, same parameters and same returned dictionary.
  - `services.llm_agent.get_agent() -> LLMAgent`: one agent per process, built on first use.
  - `LLMAgent._build_messages` stays synchronous.

- [ ] **Step 1: Write the new failing tests**

Create `backend/tests/llm/test_agent_async.py`:

```python file=backend/tests/llm/test_agent_async.py
import asyncio
import inspect
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from unittest.mock import MagicMock, patch

from llm.base import BaseLLMClient, LLMResponse
from services import llm_agent
from services.llm_agent import LLMAgent, get_agent


def _on_event_loop() -> bool:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return False
    return True


class _ProbeClient(BaseLLMClient):
    """Answers with a follow-up question and records whether it was called on the event loop."""

    def __init__(self) -> None:
        self.called_on_loop: list[bool] = []

    @property
    def model_name(self) -> str:
        return "probe"

    async def chat(self, messages, tools=None, temperature=0.2, stop=None, force_tool=None) -> LLMResponse:
        self.called_on_loop.append(_on_event_loop())
        return LLMResponse(content="Since when?", tool_calls=None, finish_reason="stop",
                           model="probe", usage={"prompt_tokens": 1, "completion_tokens": 1})


def test_respond_is_a_coroutine_function() -> None:
    assert inspect.iscoroutinefunction(LLMAgent.respond)


def test_the_agent_awaits_the_client_on_the_event_loop() -> None:
    client = _ProbeClient()
    result = asyncio.run(LLMAgent(client=client).respond("I feel dizzy", []))
    assert result["turn_type"] == "followup" and result["response"] == "Since when?"
    assert client.called_on_loop == [True]


def test_get_agent_builds_one_agent_per_process() -> None:
    with patch.object(llm_agent, "_agent", None), \
         patch.object(llm_agent, "get_llm_client", return_value=MagicMock()) as build:
        first = get_agent()
        assert get_agent() is first
    assert build.call_count == 1
```

- [ ] **Step 2: Run them and see them fail**

Run (from `backend/`): `doppler run -- pytest tests/llm/test_agent_async.py -q`
Expected: collection error, `ImportError: cannot import name 'get_agent' from 'services.llm_agent'`.

- [ ] **Step 3: Change `backend/services/llm_agent.py`**

(a) Below the line `from config import llm_provider_chain` add:

```python
from starlette.concurrency import run_in_threadpool
```

(b) In the docstring of `class LLMAgent`, replace the line

```
    Context window: last TRIAGE_CONTEXT_WINDOW messages from cache_chat.
```

with:

```
    Context window: the last TRIAGE_CONTEXT_WINDOW messages of the history the caller reads
    from the store.
```

(c) Replace `    def respond(` with `    async def respond(`.

(d) In `respond`, replace

```python
        messages = self._build_messages(user_message, history, user_profile=user_profile)
        user_turns = sum(1 for m in history if m.get("role") == "user")
        force_classify = user_turns >= self._max_followups

        return self._run(
            messages, lat, lng,
            force=force_classify,
            user_turns=user_turns,
        )
```

with:

```python
        # Off the event loop: the graph lookup can be a network call (Neo4j provider).
        messages = await run_in_threadpool(
            self._build_messages, user_message, history, user_profile=user_profile
        )
        user_turns = sum(1 for m in history if m.get("role") == "user")
        force_classify = user_turns >= self._max_followups

        return await self._run(
            messages, lat, lng,
            force=force_classify,
            user_turns=user_turns,
        )
```

(e) Replace `    def _run(` with `    async def _run(`.

(f) In `_run`, replace `        resp = self._client.chat(` with `        resp = await self._client.chat(`,
and replace

```python
                    return self._handle_triage(tool_call, messages, lat, lng, user_turns)
```

with:

```python
                    return await self._handle_triage(tool_call, messages, lat, lng, user_turns)
```

(g) Replace `    def _handle_triage(` with `    async def _handle_triage(`, and in it replace

```python
        response_text = self._generate_grounded_response(
```

with:

```python
        response_text = await self._generate_grounded_response(
```

(h) Replace `    def _generate_grounded_response(` with `    async def _generate_grounded_response(`,
and in it replace `        resp = self._client.chat(` with `        resp = await self._client.chat(`.

(i) At the very end of the file add:

```python


_agent: LLMAgent | None = None


def get_agent() -> LLMAgent:
    """The one agent of this process, built on first use. The agent keeps no conversation
    state, and its provider clients hold the HTTP connection pools, so it must be reused."""
    global _agent
    if _agent is None:
        _agent = LLMAgent()
    return _agent
```

- [ ] **Step 4: Let the evaluation scripts call the async agent**

(a) `backend/scripts/symptom_eval/system_under_test.py`: add `from llm.sync import run_sync`
next to the file's other `from llm...` / `from services...` imports, and replace

```python
        result = self._agent.respond(patient_message, history)
```

with:

```python
        result = run_sync(self._agent.respond(patient_message, history))
```

(b) `backend/scripts/symptom_eval/patient_simulator.py`: add `from llm.sync import run_sync`
next to the file's other `from llm...` imports, and replace

```python
        resp = self._client.chat(messages=messages, tools=None, temperature=0.3)
```

with:

```python
        resp = run_sync(self._client.chat(messages=messages, tools=None, temperature=0.3))
```

- [ ] **Step 5: Convert the existing agent tests**

Apply these rules to `backend/tests/llm/test_triage_tools.py`,
`backend/tests/llm/test_emergency_mismatch_logging.py`,
`backend/scripts/symptom_eval/tests/test_system_under_test.py` and
`backend/scripts/symptom_eval/tests/test_patient_simulator.py`, and to nothing else.

| Rule | Change |
|---|---|
| R1 | Add `AsyncMock` to the file's `from unittest.mock import ...` line. Add `import asyncio` to the files where R7 applies. |
| R7 | Every `agent.respond(...)` call on an `LLMAgent` becomes `asyncio.run(agent.respond(...))`. |
| R8 | A mocked client's `chat` must be awaitable: `mock_client.chat.return_value = V` becomes `mock_client.chat = AsyncMock(return_value=V)`, and `mock_client.chat.side_effect = S` becomes `mock_client.chat = AsyncMock(side_effect=S)` (the variable is named `client` in `test_emergency_mismatch_logging.py` and in `test_patient_simulator.py`, where there are three such lines). Later lines that read `mock_client.chat.call_args_list` stay as they are. |
| R9 | In `test_system_under_test.py` only: `mock_agent.respond.side_effect = _respond_side_effect` becomes `mock_agent.respond = AsyncMock(side_effect=_respond_side_effect)`. The call `adapter.respond("I have chest pain", [])` stays as it is: the adapter is synchronous. |

`test_medical_context.py` and `test_graph_context_integration.py` call `_build_messages`, which
is still synchronous: do not touch them.

- [ ] **Step 6: Run the agent tests**

Run (from `backend/`):
`doppler run -- pytest tests/llm scripts/symptom_eval/tests -q`
Expected: all pass. A `coroutine ... was never awaited` or
`can't be used in 'await' expression` failure means a missed site of R7 or R8.

- [ ] **Step 7: Check that nothing else calls the old synchronous interface**

Run (from `backend/`):
`grep -rn "\.respond(\|\.chat(" --include=*.py . | grep -v "/tests/" | grep -v __pycache__`
Expected lines, and no others outside `llm/` and `services/llm_agent.py`:
`routers/chat.py` (fixed in task 7), `scripts/symptom_eval/conversation_runner.py` and
`scripts/graphrag_eval/generate_track_b_transcripts.py` (both call the synchronous adapter),
`scripts/symptom_eval/system_under_test.py` and `scripts/symptom_eval/patient_simulator.py`
(both now through `run_sync`). Anything else: stop and report.

- [ ] **Step 8: Commit**

The chat router still calls the agent the old way, so `tests/test_chat.py` has failures until
task 7. That is expected here. Commit:

```bash
git add backend/services/llm_agent.py backend/scripts/symptom_eval/system_under_test.py backend/scripts/symptom_eval/patient_simulator.py backend/tests/llm/test_agent_async.py backend/tests/llm/test_triage_tools.py backend/tests/llm/test_emergency_mismatch_logging.py backend/scripts/symptom_eval/tests/test_system_under_test.py backend/scripts/symptom_eval/tests/test_patient_simulator.py
git commit -m "feat(agent): await the llm on the event loop and build the agent once per process"
```

---

### Task 7: History is read from the store, the chat cache is deleted

**Files:**
- Modify: `backend/services/guest_store.py`, `backend/services/chat.py`,
  `backend/routers/chat.py` (replaced)
- Delete: `backend/cache_chat.py`
- Test: `backend/tests/test_guest_store.py`, `backend/tests/test_chat_service.py`,
  `backend/tests/test_chat.py`

**Interfaces:**
- Consumes: `get_agent()` and async `respond` (task 6).
- Produces:
  - `guest_store.recent_messages(guest_id: str, session_id: str, limit: int = 20) -> list[dict]`,
    oldest first, `[]` for a bad id or a session of another guest.
  - `services.chat.get_recent_messages(session_id: str, user_id: str, limit: int = 20) -> list[dict]`.
  - `POST /chat/message` reads history through it and answers `503` when it cannot.
  - `routers.chat` imports `get_agent` and `get_recent_messages` at module level (tests patch
    `routers.chat.get_agent` and `routers.chat.get_recent_messages`).

- [ ] **Step 1: Write the failing store tests**

(a) In `backend/tests/test_guest_store.py`, directly after the function
`test_older_messages_bad_uuid_is_empty`, add:

```python
def test_recent_messages_are_the_newest_in_order_and_owned(guest) -> None:
    owner, intruder = guest(), guest()
    session = guest_store.create_session(owner, "pytest-recent")
    for i in range(5):
        guest_store.add_message(session["id"], owner, "user", f"m{i}")
    recent = guest_store.recent_messages(owner, session["id"], limit=3)
    assert [m["content"] for m in recent] == ["m2", "m3", "m4"]
    assert guest_store.recent_messages(intruder, session["id"]) == []


def test_recent_messages_bad_uuid_is_empty(guest) -> None:
    assert guest_store.recent_messages(guest(), "nope") == []
```

(b) In `backend/tests/test_chat_service.py`, replace the import line

```python
from services.chat import create_session, add_message, get_past_conversations, get_older_messages
```

with:

```python
from services.chat import (
    create_session, add_message, get_past_conversations, get_older_messages, get_recent_messages,
)
```

and add at the end of the file:

```python


class TestGetRecentMessages:
    @patch("services.chat.supabase_select")
    def test_reads_the_newest_messages_of_the_users_session_oldest_first(self, mock_select, monkeypatch):
        monkeypatch.delenv("DEMO_MODE", raising=False)
        mock_select.return_value = [{"id": "m2", "created_at": "2"}, {"id": "m1", "created_at": "1"}]

        assert get_recent_messages("s1", "u1", limit=7) == [
            {"id": "m1", "created_at": "1"}, {"id": "m2", "created_at": "2"}]

        table, params = mock_select.call_args.args
        assert table == "messages"
        assert params["session_id"] == "eq.s1" and params["user_id"] == "eq.u1"
        assert params["order"] == "created_at.desc" and params["limit"] == "7"

    @patch("services.chat.supabase_select", return_value=None)
    def test_no_rows_is_an_empty_list(self, _mock_select, monkeypatch):
        monkeypatch.delenv("DEMO_MODE", raising=False)
        assert get_recent_messages("s1", "u1") == []

    @patch("services.chat.guest_store.recent_messages", return_value=[{"id": "m1"}])
    def test_demo_mode_reads_the_guest_store(self, mock_recent, monkeypatch):
        monkeypatch.setenv("DEMO_MODE", "true")
        assert get_recent_messages("s1", "g1", limit=5) == [{"id": "m1"}]
        mock_recent.assert_called_once_with("g1", "s1", 5)
```

- [ ] **Step 2: Run them and see them fail**

Run (from `backend/`): `doppler run -- pytest tests/test_chat_service.py tests/test_guest_store.py -q`
Expected: `tests/test_chat_service.py` fails at import with
`ImportError: cannot import name 'get_recent_messages'`. In `tests/test_guest_store.py` the two
new tests fail with `AttributeError: module 'services.guest_store' has no attribute 'recent_messages'`,
or are skipped when the local rehearsal database is not running (both outcomes are fine).

- [ ] **Step 3: Add the two store functions**

(a) In `backend/services/guest_store.py`, directly after the function `get_older_messages`, add:

```python


def recent_messages(guest_id: str, session_id: str, limit: int = 20) -> list[dict]:
    """The last `limit` messages of the guest's session, oldest first."""
    if not (_is_uuid(guest_id) and _is_uuid(session_id)):
        return []
    rows = demo_db.fetch_all(
        f"""
        select {MESSAGE_COLUMNS} from messages
        where session_id = %s and guest_id = %s
        order by created_at desc
        limit %s
        """,
        (session_id, guest_id, limit),
    )
    return list(reversed(rows))
```

(b) In `backend/services/chat.py`, at the end of the file, add:

```python


def get_recent_messages(session_id: str, user_id: str, limit: int = 20) -> list[dict]:
    """
    The last `limit` messages of a session, oldest first: the context the triage agent is given.
    Read from the store on every turn, so any API process can continue any conversation.
    """
    if demo_mode():
        return guest_store.recent_messages(user_id, session_id, limit)

    msgs = supabase_select("messages", {
        "select": "*",
        "session_id": f"eq.{session_id}",
        "user_id": f"eq.{user_id}",
        "order": "created_at.desc",
        "limit": str(limit),
    }) or []
    return list(reversed(msgs))
```

Run (from `backend/`): `doppler run -- pytest tests/test_chat_service.py tests/test_guest_store.py -q`
Expected: all pass (the guest-store tests pass or are skipped).

- [ ] **Step 4: Update the router tests**

In `backend/tests/test_chat.py`:

(a) Replace `from unittest.mock import patch, MagicMock` (near the top) with
`from unittest.mock import AsyncMock, MagicMock, patch`.

(b) Delete the line `import cache_chat` and the whole `from cache_chat import (...)` block that
follows it (it imports `set_user_cache`, `get_user_cache`, `append_message_to_cache`,
`append_session_to_cache`, `invalidate_user_cache`).

(c) Replace the autouse fixture `_clear_cache` (the function decorated with
`@pytest.fixture(autouse=True)` whose docstring is "Reset module-level chat cache before and
after every test.") with:

```python
@pytest.fixture(autouse=True)
def _turn_defaults():
    """Every test gets an empty history and an agent that asks a follow-up question.
    A test overrides either with its own patch; the history mock is what the fixture yields."""
    agent = MagicMock()
    agent.respond = AsyncMock(return_value={
        "response": "Can you tell me more?", "severity": None, "reasoning": None,
        "recommended_facility": None, "nearby_facilities": [], "turn_type": "followup",
    })
    with patch("routers.chat.get_recent_messages", return_value=[]) as history, \
         patch("routers.chat.get_agent", return_value=agent):
        yield history
```

(d) Delete the whole `class TestCacheChat` (and the section comment line above it that starts
with `# ── 3. cache_chat`).

(e) In `class TestSendMessage`, delete the method `test_cache_append_called_twice`.

(f) Apply these rules everywhere in the file:

| Rule | Change |
|---|---|
| R10 | `patch("services.llm_agent.LLMAgent") as MockAgent` becomes `patch("routers.chat.get_agent") as MockAgent`. The following lines keep using `MockAgent.return_value`: it is now the agent. |
| R11 | `patch("services.llm_agent.LLMAgent", return_value=agent)` becomes `patch("routers.chat.get_agent", return_value=agent)`. |
| R12 | A mocked agent's `respond` must be awaitable. `X.respond.return_value = V` becomes `X.respond = AsyncMock(return_value=V)`. `X.respond.side_effect = S` becomes `X.respond = AsyncMock(side_effect=S)`. `X` is `mock_instance`, `MockAgent.return_value` or `agent`, depending on the test. |

(g) Replace the whole method `test_agent_and_message_writes_run_in_the_thread_pool` of
`class TestChatDoesNotBlockTheEventLoop`, and the docstring of that class, with:

```python
class TestChatDoesNotBlockTheEventLoop:
    """The agent awaits the LLM on the event loop, so no thread is held for an LLM call. The
    store calls hit the database and still run in the thread pool."""

    def test_the_agent_runs_on_the_event_loop_and_the_store_calls_in_the_thread_pool(self):
        seen: dict[str, bool] = {}

        async def respond(**_: object) -> dict:
            seen["respond"] = _on_event_loop()
            return _TRIAGE_RESULT

        def add_message(**kwargs: object) -> dict:
            seen[f"add_{kwargs['role']}"] = _on_event_loop()
            return _msg(str(kwargs["role"]))

        def recent(*_: object) -> list[dict]:
            seen["history"] = _on_event_loop()
            return []

        agent = MagicMock()
        agent.respond = respond
        with patch("routers.chat.check_rate_limit", return_value=None), \
             patch("routers.chat.get_recent_messages", side_effect=recent), \
             patch("routers.chat.add_message", side_effect=add_message), \
             patch("routers.chat.get_agent", return_value=agent), \
             patch("routers.chat.guest_store.record_event"), \
             patch("routers.chat.should_sample", return_value=False):
            resp = _guest_client().post("/chat/message", json={"session_id": FAKE_SESSION_ID, "content": "hi"})

        assert resp.status_code == 200
        assert seen == {"history": False, "add_user": False, "respond": True, "add_assistant": False}
```

(Keep the other two methods of that class, `test_session_creation_runs_in_the_thread_pool` and
`test_a_foreign_session_is_still_404_through_the_thread_pool`, below it unchanged.)

(h) At the end of the file add:

```python


# ── History comes from the store ──────────────────────────────────────────────

class TestHistoryComesFromTheStore:
    def test_history_comes_from_the_store_and_reaches_the_agent(self, _turn_defaults):
        earlier = [{"role": "user", "content": "I have a fever"},
                   {"role": "assistant", "content": "Since when?"}]
        _turn_defaults.return_value = earlier
        agent = MagicMock()
        agent.respond = AsyncMock(return_value={**_TRIAGE_RESULT, "turn_type": "followup",
                                                "recommended_facility": None})
        with patch("routers.chat.check_rate_limit", return_value=None), \
             patch("routers.chat.add_message", side_effect=[_msg("user"), _msg("assistant")]), \
             patch("routers.chat.get_agent", return_value=agent):
            resp = _guest_client().post("/chat/message", json={"session_id": FAKE_SESSION_ID, "content": "hi"})

        assert resp.status_code == 200
        assert agent.respond.call_args.kwargs["history"] == earlier
        assert _turn_defaults.call_args.args == (FAKE_SESSION_ID, FAKE_USER_ID_STR, 20)

    def test_a_failed_history_read_is_503_and_nothing_reaches_the_llm(self, _turn_defaults):
        _turn_defaults.side_effect = RuntimeError("database down")
        agent = MagicMock()
        agent.respond = AsyncMock()
        with patch("routers.chat.check_rate_limit", return_value=None), \
             patch("routers.chat.add_message") as add, \
             patch("routers.chat.get_agent", return_value=agent):
            resp = _guest_client().post("/chat/message", json={"session_id": FAKE_SESSION_ID, "content": "hi"})

        assert resp.status_code == 503
        add.assert_not_called()
        agent.respond.assert_not_called()

    def test_the_session_list_is_read_from_the_store_on_every_request(self):
        with patch("routers.chat.get_past_conversations", return_value=([], {})) as read:
            client = TestClient(_make_test_app())
            assert client.get("/chat/sessions").status_code == 200
            assert client.get("/chat/sessions").status_code == 200
        assert read.call_count == 2
```

- [ ] **Step 5: Run the router tests and see them fail**

Run (from `backend/`): `doppler run -- pytest tests/test_chat.py -q`
Expected: failures with `AttributeError: <module 'routers.chat'> does not have the attribute 'get_recent_messages'`.

- [ ] **Step 6: Replace the router and delete the cache**

Replace the whole content of `backend/routers/chat.py` with:

```python
import hashlib
import json
import logging
from datetime import datetime, date

from fastapi import APIRouter, Depends, Request, Header, BackgroundTasks
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from fastapi import HTTPException

from config import env_int
from middleware.auth import get_actor
from services import guest_store
from services.rate_limit import LLM_BUSY_RETRY_SECONDS, busy_response, check_rate_limit, client_ip
from models import CreateSessionRequest, SendMessageRequest
from services.chat import (
    generate_session_title, create_session, add_message,
    get_past_conversations, get_older_messages, get_recent_messages,
)
from services.geoapify_shadow import should_sample, log_routing_comparison
from services.llm_agent import get_agent


def _ser(obj: object) -> object:
    """Recursively convert datetime objects to ISO strings for JSONResponse."""
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: _ser(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_ser(item) for item in obj]
    return obj

router = APIRouter(prefix="/chat", tags=["chat"])
logger = logging.getLogger(__name__)


def _trunc_uid(uid: str) -> str:
    return uid[:8] + "..."


def _is_guest(actor: object) -> bool:
    return bool(getattr(actor, "is_guest", False))


async def _record_guest_event(actor: object, event_type: str, session_id: str) -> None:
    """Best-effort: an event that cannot be written never fails the request."""
    if not _is_guest(actor):
        return
    try:
        await run_in_threadpool(guest_store.record_event, str(actor.id), event_type, session_id)  # type: ignore[attr-defined]
    except Exception as exc:
        logger.warning("guest_event_failed", extra={"event_type": event_type, "error_type": type(exc).__name__})


@router.get("/sessions")
async def past_conversations(
    if_none_match: str = Header(default=""),
    current_user: object = Depends(get_actor),
) -> Response:
    """
    Returns the 5 most recent sessions with their 20 latest messages each, read from the store
    on every request. Supports ETag conditional requests — returns 304 if data unchanged.
    """
    user_id = str(current_user.id)  # type: ignore[attr-defined]

    sessions, messages = await run_in_threadpool(get_past_conversations, user_id)
    payload = _ser({"sessions": sessions, "messages": messages})
    serialized = json.dumps(payload, sort_keys=True, default=str)
    etag = f'"{hashlib.sha256(serialized.encode()).hexdigest()[:32]}"'
    logger.info("chat sessions read", extra={"user_id": _trunc_uid(user_id), "session_count": len(sessions)})

    if if_none_match == etag:
        return Response(status_code=304)

    return JSONResponse(
        content=payload,
        headers={"ETag": etag, "Cache-Control": "no-cache"},
    )


@router.post("/sessions")
async def create_new_session(
    body: CreateSessionRequest,
    request: Request,
    current_user: object = Depends(get_actor),
) -> dict:
    """Creates a new chat session. Title is derived from the first message."""
    user_id = str(current_user.id)  # type: ignore[attr-defined]
    title = generate_session_title(body.first_message)

    # Blocking database call: keep it off the event loop (see send_message).
    session = await run_in_threadpool(create_session, user_id=user_id, title=title)
    await _record_guest_event(current_user, "session_started", str(session["id"]))

    logger.info(
        "session created",
        extra={
            "request_id": getattr(request.state, "request_id", None),
            "user_id": _trunc_uid(user_id),
            "session_id": session["id"],
        },
    )
    return _ser(session)


@router.post("/message", response_model=None)
async def send_message(
    body: SendMessageRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    current_user: object = Depends(get_actor),
) -> Response | dict:
    """
    Saves a user message, runs the LLM triage agent, saves the assistant response.
    Returns user message, assistant message, and triage result (null on follow-up turns).
    """
    user_id = str(current_user.id)  # type: ignore[attr-defined]
    session_id = str(body.session_id)
    request_id = getattr(request.state, "request_id", None)

    if _is_guest(current_user):
        retry_after = await run_in_threadpool(check_rate_limit, user_id, client_ip(request))
        if retry_after is not None:
            return busy_response(retry_after)

    # History is read from the store on every turn, before this turn's message is saved: any
    # process can continue any conversation, and a restart loses nothing. A turn whose history
    # cannot be read is refused: answering without the earlier messages is worse than failing.
    try:
        history: list[dict] = await run_in_threadpool(
            get_recent_messages,
            session_id,
            user_id,
            env_int("CHAT_HISTORY_MESSAGES", 20, minimum=1, maximum=200),
        )
    except Exception as exc:
        logger.error("history_read_failed", extra={"request_id": request_id, "error_type": type(exc).__name__})
        raise HTTPException(503, "Conversation unavailable") from None

    # The store calls are blocking (database) and run in the thread pool. The agent awaits the
    # LLM on the event loop, so no thread is held for the seconds an LLM call takes.
    try:
        user_msg = await run_in_threadpool(
            add_message, session_id=session_id, user_id=user_id, role="user", content=body.content
        )
    except guest_store.SessionNotFound:
        raise HTTPException(404, "Session not found") from None

    try:
        from db import supabase_select

        user_profile: dict | None = None
        if not _is_guest(current_user):
            try:
                user_profile = await run_in_threadpool(
                    supabase_select,
                    "profile",
                    params={"user_id": f"eq.{user_id}", "select": "allergies,conditions,blood_type,medical_chat_opt_in"},
                    single=True,
                )  # type: ignore[assignment]
            except Exception as exc:
                logger.warning("profile_fetch_failed", extra={"request_id": request_id, "error": str(exc)})

        result = await get_agent().respond(
            user_message=body.content,
            history=history,
            lat=body.lat,
            lng=body.lng,
            user_profile=user_profile,
        )
    except Exception as exc:
        if getattr(exc, "status_code", None) == 429:  # provider quota: Groq and Anthropic both expose status_code
            logger.warning("llm_quota_exhausted", extra={"request_id": request_id})
            return busy_response(LLM_BUSY_RETRY_SECONDS)
        import sentry_sdk
        sentry_sdk.capture_exception(exc)
        logger.error("llm_agent_failed", extra={"request_id": request_id, "error": str(exc)})
        result = {
            "response": (
                "I'm having trouble processing your request right now. "
                "If this is an emergency, please call 911."
            ),
            "severity": None,
            "reasoning": None,
            "recommended_facility": None,
            "nearby_facilities": [],
            "turn_type": "followup",
        }

    assistant_msg = await run_in_threadpool(
        add_message, session_id=session_id, user_id=user_id, role="assistant", content=result["response"]
    )

    logger.info(
        "triage_agent_responded",
        extra={
            "request_id": request_id,
            "turn_type": result["turn_type"],
            "severity": result.get("severity"),
            "has_facility": result.get("recommended_facility") is not None,
            "nearby_count": len(result.get("nearby_facilities", [])),
        },
    )

    triage = None
    if result["turn_type"] == "triage":
        triage = {
            "severity": result["severity"],
            "reasoning": result["reasoning"],
            "recommended_facility": result["recommended_facility"],
            "nearby_facilities": result["nearby_facilities"],
        }

    if triage and triage["recommended_facility"]:
        await _record_guest_event(current_user, "recommendation_shown", session_id)

    if (
        triage
        and triage["recommended_facility"]
        and should_sample()
    ):
        background_tasks.add_task(
            log_routing_comparison, body.lat, body.lng, triage["recommended_facility"],
        )

    return _ser({"user_message": user_msg, "assistant_message": assistant_msg, "triage": triage})


@router.get("/sessions/{session_id}/messages")
async def load_older_messages(
    session_id: str,
    before_id: str,
    request: Request,
    current_user: object = Depends(get_actor),
) -> dict:
    """Cursor-based pagination — returns messages older than `before_id`, read from the store."""
    user_id = str(current_user.id)  # type: ignore[attr-defined]
    messages = await run_in_threadpool(
        get_older_messages, session_id=session_id, before_id=before_id, user_id=user_id
    )

    logger.info(
        "older messages loaded",
        extra={
            "request_id": getattr(request.state, "request_id", None),
            "user_id": _trunc_uid(user_id),
            "session_id": session_id,
            "count": len(messages),
        },
    )
    return _ser({"messages": messages})


@router.post("/sessions/invalidate")
async def invalidate_cache(
    current_user: object = Depends(get_actor),
) -> dict:
    """Kept for the web app's logout call. The server holds no chat cache any more:
    conversations are read from the store on every request, so there is nothing to clear."""
    return {"status": "cache cleared"}
```

Delete the file `backend/cache_chat.py`:

```bash
git rm backend/cache_chat.py
```

Check that nothing imports it any more (from `backend/`):
`grep -rn "cache_chat" --include=*.py . | grep -v __pycache__`
Expected: no output. If a line appears, stop and report it.

- [ ] **Step 7: Run the tests**

Run (from `backend/`): `doppler run -- pytest tests/test_chat.py -q`
Expected: all pass.

Run the whole backend suite: `doppler run -- pytest -q`
Expected: no failure (the failures left by tasks 5 and 6 are gone).

- [ ] **Step 8: Commit**

```bash
git add backend/services/guest_store.py backend/services/chat.py backend/routers/chat.py backend/tests/test_guest_store.py backend/tests/test_chat_service.py backend/tests/test_chat.py
git commit -m "feat(chat): read history from the store on every turn and drop the in-process chat cache"
```

(`git rm` already staged the deletion of `backend/cache_chat.py`.)

---

### Task 8: Admission control

**Files:**
- Create: `backend/services/admission.py`
- Modify: `backend/metrics.py`, `backend/routers/chat.py`
- Test: `backend/tests/test_admission.py` (new), `backend/tests/test_chat.py`

**Interfaces:**
- Produces:
  - `admission.admit()`: a context manager. Raises `admission.Busy` when
    `MAX_TURNS_IN_FLIGHT` (default 0, meaning no limit) turns are already in flight.
  - `admission.in_flight() -> int`, `admission.retry_after_seconds(rng=random.random) -> int`,
    `admission.reset_for_tests() -> None`.
  - Metrics `chat_turns_in_flight` (gauge) and `chat_turns_rejected_total` (counter).
  - `POST /chat/message` answers `429 {"code": "busy", "retry_after": N}` at once when refused,
    before the rate limit and before any write.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_admission.py`:

```python file=backend/tests/test_admission.py
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from observability import _registry
from services import admission


@pytest.fixture(autouse=True)
def _clean(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("MAX_TURNS_IN_FLIGHT", raising=False)
    monkeypatch.delenv("ADMISSION_RETRY_SECONDS", raising=False)
    admission.reset_for_tests()
    yield
    admission.reset_for_tests()


def test_without_a_limit_every_turn_is_admitted() -> None:
    with admission.admit():
        with admission.admit():
            assert admission.in_flight() == 2
    assert admission.in_flight() == 0


def test_at_the_limit_the_next_turn_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAX_TURNS_IN_FLIGHT", "1")
    with admission.admit():
        with pytest.raises(admission.Busy):
            with admission.admit():
                pass
        assert admission.in_flight() == 1
    assert admission.in_flight() == 0


def test_a_turn_that_raises_still_frees_its_slot(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAX_TURNS_IN_FLIGHT", "1")
    with pytest.raises(ValueError):
        with admission.admit():
            raise ValueError("turn failed")
    with admission.admit():
        assert admission.in_flight() == 1


def test_a_refused_turn_is_counted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAX_TURNS_IN_FLIGHT", "1")
    before = _registry.get_sample_value("chat_turns_rejected_total") or 0
    with admission.admit():
        with pytest.raises(admission.Busy):
            with admission.admit():
                pass
    assert _registry.get_sample_value("chat_turns_rejected_total") == before + 1


def test_the_gauge_reads_the_turns_in_flight() -> None:
    with admission.admit():
        assert _registry.get_sample_value("chat_turns_in_flight") == 1
    assert _registry.get_sample_value("chat_turns_in_flight") == 0


def test_a_bad_limit_means_no_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAX_TURNS_IN_FLIGHT", "many")
    with admission.admit():
        with admission.admit():
            assert admission.in_flight() == 2


def test_the_retry_delay_is_the_setting_plus_up_to_two_seconds(monkeypatch: pytest.MonkeyPatch) -> None:
    assert admission.retry_after_seconds(lambda: 0.0) == 3
    assert admission.retry_after_seconds(lambda: 0.999) == 5
    monkeypatch.setenv("ADMISSION_RETRY_SECONDS", "7")
    assert admission.retry_after_seconds(lambda: 0.0) == 7
```

In `backend/tests/test_chat.py`, inside `class TestGuestChat`, add these two methods at the end
of the class:

```python
    def test_a_refused_turn_stores_nothing_and_does_not_count_against_the_rate_limit(self, monkeypatch, _turn_defaults):
        from services import admission

        monkeypatch.setenv("MAX_TURNS_IN_FLIGHT", "1")
        monkeypatch.setattr(admission, "_in_flight", 1)
        monkeypatch.setattr(admission, "retry_after_seconds", lambda: 4)
        with patch("routers.chat.check_rate_limit") as limit, \
             patch("routers.chat.add_message") as add:
            resp = _guest_client().post("/chat/message", json={"session_id": FAKE_SESSION_ID, "content": "hi"})

        assert resp.status_code == 429 and resp.json() == {"code": "busy", "retry_after": 4}
        assert resp.headers["retry-after"] == "4"
        limit.assert_not_called()
        add.assert_not_called()
        _turn_defaults.assert_not_called()

    def test_an_admitted_turn_frees_its_slot_when_it_ends(self, monkeypatch):
        from services import admission

        monkeypatch.setenv("MAX_TURNS_IN_FLIGHT", "1")
        monkeypatch.setattr(admission, "_in_flight", 0)
        with patch("routers.chat.check_rate_limit", return_value=None), \
             patch("routers.chat.add_message",
                   side_effect=[_msg("user"), _msg("assistant"), _msg("user"), _msg("assistant")]):
            client = _guest_client()
            first = client.post("/chat/message", json={"session_id": FAKE_SESSION_ID, "content": "hi"})
            second = client.post("/chat/message", json={"session_id": FAKE_SESSION_ID, "content": "again"})

        assert first.status_code == 200 and second.status_code == 200
        assert admission.in_flight() == 0
```

- [ ] **Step 2: Run them and see them fail**

Run (from `backend/`): `doppler run -- pytest tests/test_admission.py -q`
Expected: collection error, `ImportError: cannot import name 'admission' from 'services'`.

- [ ] **Step 3: Add the metrics**

In `backend/metrics.py`:

(a) Directly below the line that defines `POOL_WAITING`, add:

```python
TURNS_IN_FLIGHT = Gauge(
    "chat_turns_in_flight", "Chat turns admitted and not yet answered, in this process", registry=_registry,
)
TURNS_REJECTED = Counter(
    "chat_turns_rejected_total", "Chat turns refused at the admission limit", registry=_registry,
)
```

(b) At the end of the file add:

```python


def bind_turns_in_flight(read_count: Callable[[], int]) -> None:
    """Makes the turns-in-flight gauge read `read_count()` at scrape time. Called once by admission."""
    TURNS_IN_FLIGHT.set_function(read_count)
```

- [ ] **Step 4: Write the admission module**

Create `backend/services/admission.py`:

```python file=backend/services/admission.py
"""Admission control for chat turns: a limit on turns in flight in this process.

Past the limit a turn is refused at once instead of queued: an overloaded process answers
"busy" quickly rather than answering everyone slowly. The count lives in the process, so each
replica protects itself and capacity adds up when replicas are added. MAX_TURNS_IN_FLIGHT is 0
(no limit) until it is set from a measured breakpoint.

All of this runs on the event loop thread, between awaits, so the counter needs no lock.
"""
import random
from collections.abc import Callable, Iterator
from contextlib import contextmanager

import metrics
from config import env_int

RETRY_JITTER_SECONDS = 3  # 0, 1 or 2 extra seconds, so refused turns do not come back together


class Busy(Exception):
    """The process already has MAX_TURNS_IN_FLIGHT turns in flight."""


_in_flight = 0


def in_flight() -> int:
    return _in_flight


metrics.bind_turns_in_flight(in_flight)


@contextmanager
def admit() -> Iterator[None]:
    """Counts one turn in flight for the length of the block. Raises Busy at the limit."""
    global _in_flight
    limit = env_int("MAX_TURNS_IN_FLIGHT", 0, minimum=0, maximum=100000)
    if limit and _in_flight >= limit:
        metrics.TURNS_REJECTED.inc()
        raise Busy()
    _in_flight += 1
    try:
        yield
    finally:
        _in_flight -= 1


def retry_after_seconds(rng: Callable[[], float] = random.random) -> int:
    base = env_int("ADMISSION_RETRY_SECONDS", 3, minimum=1, maximum=60)
    return base + int(rng() * RETRY_JITTER_SECONDS)


def reset_for_tests() -> None:
    global _in_flight
    _in_flight = 0
```

Run (from `backend/`): `doppler run -- pytest tests/test_admission.py -q`
Expected: 7 passed.

- [ ] **Step 5: Put the check in front of the turn**

In `backend/routers/chat.py`:

(a) Replace the line `from services import guest_store` with:

```python
from services import admission, guest_store
```

(b) Replace this block (the decorator, signature and docstring of `send_message`, and its first
three statements):

```python
@router.post("/message", response_model=None)
async def send_message(
    body: SendMessageRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    current_user: object = Depends(get_actor),
) -> Response | dict:
    """
    Saves a user message, runs the LLM triage agent, saves the assistant response.
    Returns user message, assistant message, and triage result (null on follow-up turns).
    """
    user_id = str(current_user.id)  # type: ignore[attr-defined]
```

with:

```python
@router.post("/message", response_model=None)
async def send_message(
    body: SendMessageRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    current_user: object = Depends(get_actor),
) -> Response | dict:
    """
    Admits the turn, or answers "busy" at once when this process is at its limit. The check
    comes before the rate limit and before any write: a refused turn stores nothing and does
    not use the guest's allowance, so the client can simply send it again.
    """
    try:
        with admission.admit():
            return await _run_turn(body, request, background_tasks, current_user)
    except admission.Busy:
        return busy_response(admission.retry_after_seconds())


async def _run_turn(
    body: SendMessageRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    current_user: object,
) -> Response | dict:
    """
    Saves a user message, runs the LLM triage agent, saves the assistant response.
    Returns user message, assistant message, and triage result (null on follow-up turns).
    """
    user_id = str(current_user.id)  # type: ignore[attr-defined]
```

- [ ] **Step 6: Run the tests**

Run (from `backend/`): `doppler run -- pytest tests/test_admission.py tests/test_chat.py -q`
Expected: all pass.

Run the whole backend suite: `doppler run -- pytest -q`
Expected: no failure.

- [ ] **Step 7: Commit**

```bash
git add backend/services/admission.py backend/metrics.py backend/routers/chat.py backend/tests/test_admission.py backend/tests/test_chat.py
git commit -m "feat(chat): refuse turns past a limit on turns in flight instead of queueing them"
```

---

### Task 9: The chat waits and retries by itself on a short busy answer

**Files:**
- Modify: `webapp/src/lib/busy.ts`, `webapp/src/hooks/useConversations.ts`
- Test: `webapp/src/lib/busy.test.ts` (replaced)

**Interfaces:**
- Consumes: the busy answer `429 {"code": "busy", "retry_after": N}` (task 8 sends N of 3 to 5;
  the rate limit and the provider quota send 60 or more).
- Produces:
  - `nextBusyStep(retryAfterSeconds: number, attempt: number): BusyStep` where
    `BusyStep = { kind: "retry" | "busy"; waitMs: number }`.
  - `busyMessage(busyUntil, now)`: a seconds text for a wait of 10 seconds or less, the minutes
    text otherwise, both ending with the emergency line.
  - Constants `EMERGENCY_LINE`, `SHORT_WAIT_SECONDS = 10`, `MAX_AUTO_RETRIES = 3`.
- No component changes: `ChatPanel` and `MobileLayout` already render `busyMessage(busyUntil, ...)`
  and already disable sending while `busyUntil` is set.

- [ ] **Step 1: Replace the test**

Replace the whole content of `webapp/src/lib/busy.test.ts` with:

```ts
import { describe, expect, it } from "vitest"
import { busyMessage, EMERGENCY_LINE, MAX_AUTO_RETRIES, nextBusyStep } from "./busy"

describe("busyMessage", () => {
  it("rounds a long wait up to whole minutes", () => {
    expect(busyMessage(61_000, 0)).toBe(
      "MediCoord is busy right now. Try again in about 2 minutes. If this is an emergency, call 911.")
  })

  it("uses the singular for one minute", () => {
    expect(busyMessage(60_000, 0)).toBe(
      "MediCoord is busy right now. Try again in about 1 minute. If this is an emergency, call 911.")
  })

  it("says it is retrying when the wait is ten seconds or less", () => {
    expect(busyMessage(10_000, 0)).toBe(
      "High demand, retrying in 10 seconds. If this is an emergency, call 911.")
    expect(busyMessage(1_000, 0)).toBe(
      "High demand, retrying in 1 second. If this is an emergency, call 911.")
  })

  it("never says zero or a negative number of seconds", () => {
    expect(busyMessage(0, 5_000)).toBe(
      "High demand, retrying in 1 second. If this is an emergency, call 911.")
  })

  it("always carries the emergency line", () => {
    expect(busyMessage(3_000, 0).endsWith(EMERGENCY_LINE)).toBe(true)
    expect(busyMessage(600_000, 0).endsWith(EMERGENCY_LINE)).toBe(true)
  })
})

describe("nextBusyStep", () => {
  it("retries by itself after a short wait", () => {
    expect(nextBusyStep(3, 0)).toEqual({ kind: "retry", waitMs: 3_000 })
    expect(nextBusyStep(10, MAX_AUTO_RETRIES - 1)).toEqual({ kind: "retry", waitMs: 10_000 })
  })

  it("stops retrying after the allowed attempts and asks to try again in a minute", () => {
    expect(nextBusyStep(3, MAX_AUTO_RETRIES)).toEqual({ kind: "busy", waitMs: 60_000 })
  })

  it("does not retry by itself on a long wait", () => {
    expect(nextBusyStep(11, 0)).toEqual({ kind: "busy", waitMs: 11_000 })
    expect(nextBusyStep(600, 0)).toEqual({ kind: "busy", waitMs: 600_000 })
  })

  it("treats a missing or zero wait as one second", () => {
    expect(nextBusyStep(0, 0)).toEqual({ kind: "retry", waitMs: 1_000 })
  })
})
```

- [ ] **Step 2: Run it and see it fail**

Run (from `webapp/`): `doppler run -- npm run test -- src/lib/busy.test.ts`
Expected: FAIL, `nextBusyStep is not a function` (and the message assertions fail on the
missing emergency line).

- [ ] **Step 3: Replace `webapp/src/lib/busy.ts`**

```ts
export const EMERGENCY_LINE = "If this is an emergency, call 911."
/** A busy answer asking for this many seconds or fewer is retried without the guest doing anything. */
export const SHORT_WAIT_SECONDS = 10
export const MAX_AUTO_RETRIES = 3
const GIVE_UP_WAIT_SECONDS = 60

export interface BusyStep {
  kind: "retry" | "busy"
  waitMs: number
}

/**
 * What to do with a busy answer. `attempt` is how many automatic retries this message has
 * already had. A short wait is retried, up to MAX_AUTO_RETRIES times; a long one, or a short
 * one after the last retry, is shown to the guest.
 */
export function nextBusyStep(retryAfterSeconds: number, attempt: number): BusyStep {
  const seconds = Math.max(1, retryAfterSeconds)
  if (seconds > SHORT_WAIT_SECONDS) return { kind: "busy", waitMs: seconds * 1000 }
  if (attempt < MAX_AUTO_RETRIES) return { kind: "retry", waitMs: seconds * 1000 }
  return { kind: "busy", waitMs: GIVE_UP_WAIT_SECONDS * 1000 }
}

export function busyMessage(busyUntil: number, now: number): string {
  const remainingMs = busyUntil - now
  if (remainingMs <= SHORT_WAIT_SECONDS * 1000) {
    const seconds = Math.max(1, Math.ceil(remainingMs / 1000))
    return `High demand, retrying in ${seconds} second${seconds === 1 ? "" : "s"}. ${EMERGENCY_LINE}`
  }
  const minutes = Math.max(1, Math.ceil(remainingMs / 60_000))
  return `MediCoord is busy right now. Try again in about ${minutes} minute${minutes === 1 ? "" : "s"}. ${EMERGENCY_LINE}`
}
```

- [ ] **Step 4: Retry in the hook**

In `webapp/src/hooks/useConversations.ts`:

(a) Below the line `import { apiFetch } from "../lib/apiClient"` add:

```ts
import { nextBusyStep } from "../lib/busy"
```

(b) Replace the whole `sendMessage` function (from `const sendMessage = async (` to its closing
`}` just before `const loadOlderMessages`) with:

```ts
  const sendMessage = async (
    sessionId: string,
    content: string,
    coords?: { lat: number; lng: number } | null,
  ): Promise<ChatMessageResponse | null> => {
    // A refused turn stored nothing on the server, so sending it again cannot duplicate it.
    for (let attempt = 0; ; attempt += 1) {
      const res = await apiFetch("/chat/message", {
        method: "POST",
        body: JSON.stringify({
          session_id: sessionId,
          content,
          ...(coords ? { lat: coords.lat, lng: coords.lng } : {}),
        }),
      })
      if (res.status === 429) {
        const body = await res.json().catch(() => null) as BusyResponse | null
        const step = nextBusyStep(body?.retry_after ?? 60, attempt)
        if (busyTimerRef.current) clearTimeout(busyTimerRef.current)
        setBusyUntil(Date.now() + step.waitMs)
        if (step.kind === "retry") {
          await new Promise<void>(resolve => { setTimeout(resolve, step.waitMs) })
          setBusyUntil(null)
          continue
        }
        busyTimerRef.current = setTimeout(() => setBusyUntil(null), step.waitMs)
        return null
      }
      if (!res.ok) return null
      const data: ChatMessageResponse = await res.json()
      setCache((prev: ConversationsCache | null) => {
        if (!prev) return prev
        const existing = prev.messages[sessionId] ?? []
        return {
          ...prev,
          messages: { ...prev.messages, [sessionId]: [...existing, data.user_message, data.assistant_message] },
        }
      })
      return data
    }
  }
```

- [ ] **Step 5: Check types and tests**

Run (from `webapp/`): `npx tsc -b` — expected: no error.
Run (from `webapp/`): `doppler run -- npm run test` — expected: all pass. If another test file
asserts the old busy text without the emergency line, add the emergency line to its expected
text; change nothing else in it.

- [ ] **Step 6: Commit**

```bash
git add webapp/src/lib/busy.ts webapp/src/lib/busy.test.ts webapp/src/hooks/useConversations.ts
git commit -m "feat(web): wait and retry by itself on a short busy answer, with the emergency line"
```

---

## CHECKPOINT 2

Stop here. Report: the five commit hashes, the output of the whole backend suite and the web
suite, every site where a conversion rule was applied outside the listed files, and anything
that did not apply as written. Wait for review.

---

# Part 3: recommendation and route drawing (spec section 7)

### Task 10: Candidate lookup through a cell index

**Files:**
- Modify: `backend/requirements.txt`, `backend/services/proximity.py`
- Create: `backend/services/cell_index.py`, `backend/scripts/perf_baseline/bench_lookup.py`
- Test: `backend/tests/test_cell_index.py` (new). The existing
  `backend/tests/test_proximity_within.py` and `backend/tests/llm/test_triage_tools.py` must
  stay green without edits.

**Interfaces:**
- Produces:
  - `cell_index.cell_of(lat: float, lng: float, resolution: int) -> str`.
  - `cell_index.nearest(facilities, lat, lng, accepts, count, distance_km) -> list[tuple[int, dict]] | None`
    and `cell_index.within_radius(facilities, lat, lng, radius_km) -> list[tuple[int, dict]] | None`.
    Each entry is `(position in the facility list, facility)`. `None` means "scan the whole list".
  - `cell_index.rings_covering(distance_km: float) -> int`, `cell_index.MAX_RINGS = 40`,
    `cell_index.MIN_INDEXED = 1000`: below that many facilities both functions return `None`
    and the caller scans. Measured on 2026-10-10: at 304 facilities the scan takes 0.12 ms and
    the index 0.18 to 0.70 ms; at 1,000 the index is already faster (0.11 to 0.29 ms against
    0.40 ms); at 100,000 it is 0.47 ms against 59 ms.
  - `find_nearest_facilities` and `find_facilities_within` keep their signatures and return
    exactly what they returned before, in the same order.

- [ ] **Step 1: Add the dependency**

Append this line to `backend/requirements.txt`:

```
h3==4.*
```

Install it into the one Python environment:

```bash
source /home/niki/Documents/workenv/pydev/bin/activate
pip install -r backend/requirements.txt
```

Expected: `Successfully installed h3-4...` (other requirements already satisfied).

- [ ] **Step 2: Write the failing tests**

Create `backend/tests/test_cell_index.py`:

```python file=backend/tests/test_cell_index.py
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import patch

import pytest

from services import cell_index, proximity
from services.proximity import DRIVE_MPS, TRANSIT_MPS, WALK_MPS, haversine_km

TORONTO = (43.6532, -79.3832)
OTTAWA = (45.4215, -75.6972)
SEVERITIES = ("routine", "moderate", "urgent", "emergent")
CATEGORIES = ("hospital", "ambulatory", "residential")


@pytest.fixture(autouse=True)
def _always_indexed(monkeypatch: pytest.MonkeyPatch) -> None:
    """These tests are about the index: use it whatever the size of the list."""
    monkeypatch.setattr(cell_index, "MIN_INDEXED", 0)


def _facilities(count: int, seed: int, spread: float = 0.25) -> list[dict]:
    rng = random.Random(seed)
    return [
        {
            "id": f"f{i}", "name": f"Facility {i}", "category": rng.choice(CATEGORIES),
            "address": f"{i} Main St", "phone": None,
            "lat": TORONTO[0] + rng.uniform(-spread, spread),
            "lng": TORONTO[1] + rng.uniform(-spread, spread),
            "accepted_severity": rng.sample(SEVERITIES, rng.randint(1, 4)),
        }
        for i in range(count)
    ]


def _scan_nearest(facilities: list[dict], lat: float, lng: float, severity: str, top_n: int) -> list[dict]:
    """The lookup as it was before the index: every facility, then a stable sort by distance."""
    eligible = [f for f in facilities if severity in f.get("accepted_severity", [])]
    ranked = sorted(
        [{**f, "distanceKm": round(haversine_km(lat, lng, f["lat"], f["lng"]), 2)} for f in eligible],
        key=lambda x: x["distanceKm"],
    )
    return ranked[:top_n]


def _scan_within(facilities: list[dict], lat: float, lng: float, radius_m: int, category: str | None) -> list[dict]:
    """find_facilities_within as it was before the index."""
    radius = min(radius_m, proximity.MAX_RADIUS_M)
    rows: list[dict] = []
    for f in facilities:
        if category is not None and f.get("category") != category:
            continue
        distance_m = round(haversine_km(lat, lng, f["lat"], f["lng"]) * 1000)
        if distance_m > radius:
            continue
        rows.append({
            "facility_id": str(f["id"]), "facility_name": f["name"], "category": f["category"],
            "address": f.get("address") or "", "phone": f.get("phone"), "is_operational": True,
            "distance_m": distance_m,
            "eta_walk_min": round(distance_m / WALK_MPS / 60),
            "eta_transit_min": round(distance_m / TRANSIT_MPS / 60),
            "eta_drive_min": round(distance_m / DRIVE_MPS / 60),
        })
    rows.sort(key=lambda row: row["distance_m"])
    return rows[:proximity.NEARBY_LIMIT]


def _nearest(facilities: list[dict] | None, lat: float, lng: float, severity: str, top_n: int = 3):
    with patch("services.proximity.get_cached_facilities", return_value=(facilities, '"v"')):
        return proximity.find_nearest_facilities(lat, lng, severity, top_n)


def _within(facilities: list[dict], lat: float, lng: float, radius_m: int, category: str | None):
    with patch("services.proximity.get_cached_facilities", return_value=(facilities, '"v"')):
        return proximity.find_facilities_within(lat, lng, radius_m, category)


@pytest.mark.parametrize("count, seed", [(304, 1), (3000, 2)])
def test_the_index_gives_exactly_the_answer_of_the_scan(count: int, seed: int) -> None:
    facilities = _facilities(count, seed)
    rng = random.Random(seed + 100)
    for _ in range(200):
        lat = TORONTO[0] + rng.uniform(-0.3, 0.3)
        lng = TORONTO[1] + rng.uniform(-0.3, 0.3)
        severity = rng.choice(SEVERITIES)
        top_n = rng.choice([1, 3, 5])
        assert _nearest(facilities, lat, lng, severity, top_n) == _scan_nearest(facilities, lat, lng, severity, top_n)


def test_a_guest_far_from_every_facility_gets_the_same_answer_as_the_scan() -> None:
    facilities = _facilities(304, 3)
    result = _nearest(facilities, *OTTAWA, "urgent")
    assert result == _scan_nearest(facilities, *OTTAWA, "urgent", 3)
    assert len(result) == 3


def test_a_severity_few_facilities_accept_is_still_found() -> None:
    facilities = _facilities(304, 4)
    for facility in facilities:
        facility["accepted_severity"] = ["routine"]
    facilities[17]["accepted_severity"] = ["emergent"]
    facilities[250]["accepted_severity"] = ["emergent"]
    result = _nearest(facilities, *TORONTO, "emergent")
    assert result == _scan_nearest(facilities, *TORONTO, "emergent", 3)
    assert {f["id"] for f in result} == {"f17", "f250"}


def test_no_facility_accepting_the_severity_is_an_empty_list() -> None:
    facilities = _facilities(50, 5)
    for facility in facilities:
        facility["accepted_severity"] = ["routine"]
    assert _nearest(facilities, *TORONTO, "emergent") == []


def test_an_empty_list_is_empty_and_no_list_is_none() -> None:
    assert _nearest([], *TORONTO, "urgent") == []
    assert _nearest(None, *TORONTO, "urgent") is None


@pytest.mark.parametrize("radius_m", [500, 5000, 20000, 60000])
def test_facilities_within_a_radius_match_the_scan(radius_m: int) -> None:
    facilities = _facilities(304, 6)
    rng = random.Random(radius_m)
    for _ in range(50):
        lat = TORONTO[0] + rng.uniform(-0.3, 0.3)
        lng = TORONTO[1] + rng.uniform(-0.3, 0.3)
        category = rng.choice([None, "hospital"])
        assert _within(facilities, lat, lng, radius_m, category) == _scan_within(facilities, lat, lng, radius_m, category)


def test_the_index_follows_a_replaced_facility_list() -> None:
    first, second = _facilities(60, 7), _facilities(60, 8)
    assert _nearest(first, *TORONTO, "urgent") == _scan_nearest(first, *TORONTO, "urgent", 3)
    assert _nearest(second, *TORONTO, "urgent") == _scan_nearest(second, *TORONTO, "urgent", 3)


def test_a_short_list_is_left_to_the_scan(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cell_index, "MIN_INDEXED", 1000)
    facilities = _facilities(304, 9)
    assert cell_index.nearest(facilities, *TORONTO, lambda f: True, 3, lambda f: 0.0) is None
    assert cell_index.within_radius(facilities, *TORONTO, 5.0) is None
    assert _nearest(facilities, *TORONTO, "urgent") == _scan_nearest(facilities, *TORONTO, "urgent", 3)
    assert _within(facilities, *TORONTO, 5000, None) == _scan_within(facilities, *TORONTO, 5000, None)


def test_the_rings_needed_grow_with_the_distance() -> None:
    assert cell_index.rings_covering(0) >= 1
    assert cell_index.rings_covering(1) < cell_index.rings_covering(5) < cell_index.rings_covering(15)
    assert cell_index.rings_covering(19) <= cell_index.MAX_RINGS < cell_index.rings_covering(25)
```

- [ ] **Step 3: Run them and see them fail**

Run (from `backend/`): `doppler run -- pytest tests/test_cell_index.py -q`
Expected: collection error, `ImportError: cannot import name 'cell_index' from 'services'`.

- [ ] **Step 4: Write the index**

Create `backend/services/cell_index.py`:

```python file=backend/services/cell_index.py
"""Facilities filed by H3 cell.

A lookup reads the cells around a point instead of every facility, so its cost depends on how
many facilities are nearby, not on how many exist. The index is rebuilt when the facility list
object changes: the facility cache replaces its list, it never edits it in place.
"""
import math
from collections.abc import Callable

import h3

RESOLUTION = 8
# Bounds on the edge of a resolution-8 cell (0.46 km on average; the grid stretches a little).
EDGE_KM_MIN = 0.35
EDGE_KM_MAX = 0.60
MAX_RINGS = 40  # covers about 20 km; beyond that a scan of the whole list is the cheaper answer
# Below this many facilities the scan is as fast or faster (measured: 0.12 ms for 304 facilities
# against 0.18 to 0.70 ms through the cells), so the index is not used.
MIN_INDEXED = 1000
_GROWTH = (1, 2, 4, 8, 16, 32, MAX_RINGS)

Entry = tuple[int, dict]  # (position in the facility list, facility)

_cells: dict[str, list[Entry]] = {}
_built_for: list[dict] | None = None


def cell_of(lat: float, lng: float, resolution: int) -> str:
    return h3.latlng_to_cell(lat, lng, resolution)


def _ensure(facilities: list[dict]) -> dict[str, list[Entry]]:
    global _cells, _built_for
    if _built_for is not facilities:
        cells: dict[str, list[Entry]] = {}
        for position, facility in enumerate(facilities):
            if facility.get("lat") is None or facility.get("lng") is None:
                continue
            cell = cell_of(facility["lat"], facility["lng"], RESOLUTION)
            cells.setdefault(cell, []).append((position, facility))
        _cells, _built_for = cells, facilities
    return _cells


def rings_covering(distance_km: float) -> int:
    """Rings around a point's cell that are sure to contain everything within `distance_km`.

    Two cells g rings apart have centres at least 1.5 * edge * g apart, and a point is at most
    one edge from the centre of its cell. With the smallest and the largest edge this gives
    distance >= 1.5 * EDGE_KM_MIN * g - 2 * EDGE_KM_MAX, solved here for g.
    """
    return math.floor((distance_km + 2 * EDGE_KM_MAX) / (1.5 * EDGE_KM_MIN)) + 1


def _within_rings(cells: dict[str, list[Entry]], lat: float, lng: float, rings: int) -> list[Entry]:
    origin = cell_of(lat, lng, RESOLUTION)
    return [entry for cell in h3.grid_disk(origin, rings) for entry in cells.get(cell, ())]


def nearest(
    facilities: list[dict],
    lat: float,
    lng: float,
    accepts: Callable[[dict], bool],
    count: int,
    distance_km: Callable[[dict], float],
) -> list[Entry] | None:
    """Entries sure to include the `count` nearest facilities that pass `accepts`.

    None when the list is short (MIN_INDEXED), or when the rings cannot guarantee the answer
    within MAX_RINGS (few matches, or all far away): the caller then scans the whole list,
    which is always correct.
    """
    if count < 1:
        return []
    if len(facilities) < MIN_INDEXED:
        return None
    cells = _ensure(facilities)
    for rings in _GROWTH:
        found = [entry for entry in _within_rings(cells, lat, lng, rings) if accepts(entry[1])]
        if len(found) < count:
            continue
        farthest_needed = sorted(distance_km(facility) for _, facility in found)[count - 1]
        needed = rings_covering(farthest_needed)
        if needed <= rings:
            return found
        if needed > MAX_RINGS:
            return None
        return [entry for entry in _within_rings(cells, lat, lng, needed) if accepts(entry[1])]
    return None


def within_radius(facilities: list[dict], lat: float, lng: float, radius_km: float) -> list[Entry] | None:
    """Entries sure to include every facility within `radius_km`. None when the list is short
    (MIN_INDEXED) or the radius needs more than MAX_RINGS: the caller then scans the whole list."""
    if len(facilities) < MIN_INDEXED:
        return None
    rings = rings_covering(radius_km)
    if rings > MAX_RINGS:
        return None
    return _within_rings(_ensure(facilities), lat, lng, rings)
```

- [ ] **Step 5: Use it in the two lookups**

In `backend/services/proximity.py`:

(a) Replace the import lines at the top

```python
import math
import os
from cache import get_cached_facilities
```

with:

```python
import math
import os
from cache import get_cached_facilities
from services import cell_index
```

(b) In `find_nearest_facilities`, replace everything from the line
`    facilities, _ = get_cached_facilities()` to the end of the function (`    return ranked[:top_n]`)
with:

```python
    facilities, _ = get_cached_facilities()
    if facilities is None:
        return None

    def accepts(f: dict) -> bool:
        return severity in f.get("accepted_severity", [])

    def distance(f: dict) -> float:
        return haversine_km(lat, lng, f["lat"], f["lng"])

    entries = cell_index.nearest(facilities, lat, lng, accepts, top_n, distance)
    if entries is None:  # a short list, few matches or all far away: scan, which is always correct
        entries = [(position, f) for position, f in enumerate(facilities) if accepts(f)]
    if not entries:
        return []

    # Ties keep the order of the facility list, exactly as the full scan did.
    ranked = sorted(
        ((round(distance(f), 2), position, f) for position, f in entries),
        key=lambda item: (item[0], item[1]),
    )
    return [{**f, "distanceKm": km} for km, _, f in ranked[:top_n]]
```

(c) In `find_facilities_within`, replace everything from the line
`    radius = min(radius_m, MAX_RADIUS_M)` to the end of the function with:

```python
    radius = min(radius_m, MAX_RADIUS_M)
    entries = cell_index.within_radius(facilities, lat, lng, radius / 1000)
    if entries is None:  # a short list, or a radius too wide for the cells: look at every facility
        entries = list(enumerate(facilities))

    rows: list[tuple[int, int, dict]] = []
    for position, f in entries:
        if category is not None and f.get("category") != category:
            continue
        if f.get("lat") is None or f.get("lng") is None:
            continue
        distance_m = round(haversine_km(lat, lng, f["lat"], f["lng"]) * 1000)
        if distance_m > radius:
            continue
        rows.append((distance_m, position, {
            "facility_id":     str(f["id"]),
            "facility_name":   f["name"],
            "category":        f["category"],
            "address":         f.get("address") or "",
            "phone":           f.get("phone"),
            "is_operational":  True,
            "distance_m":      distance_m,
            "eta_walk_min":    round(distance_m / WALK_MPS / 60),
            "eta_transit_min": round(distance_m / TRANSIT_MPS / 60),
            "eta_drive_min":   round(distance_m / DRIVE_MPS / 60),
        }))

    # Ties keep the order of the facility list, exactly as the full scan did.
    rows.sort(key=lambda row: (row[0], row[1]))
    return [row for _, _, row in rows[:NEARBY_LIMIT]]
```

- [ ] **Step 6: Run the tests**

Run (from `backend/`):
`doppler run -- pytest tests/test_cell_index.py tests/test_proximity_within.py tests/llm/test_triage_tools.py -q`
Expected: all pass, with no edit to the two existing files.

- [ ] **Step 7: Add the benchmark script**

Create `backend/scripts/perf_baseline/bench_lookup.py`:

```python file=backend/scripts/perf_baseline/bench_lookup.py
"""Times the nearest-facility lookup with and without the cell index, on synthetic facilities.

Run from backend/:  python -m scripts.perf_baseline.bench_lookup
Prints one row per facility count. No network, no database.
"""
import random
import time

from services import cell_index
from services.proximity import haversine_km

CENTRE = (43.6532, -79.3832)
SEVERITIES = ("routine", "moderate", "urgent", "emergent")
LOOKUPS = 200
TOP_N = 3


def synthetic(count: int, seed: int = 1, spread: float = 0.6) -> list[dict]:
    rng = random.Random(seed)
    return [
        {"id": f"f{i}", "name": f"Facility {i}",
         "lat": CENTRE[0] + rng.uniform(-spread, spread), "lng": CENTRE[1] + rng.uniform(-spread, spread),
         "accepted_severity": rng.sample(SEVERITIES, rng.randint(1, 4))}
        for i in range(count)
    ]


def _points(seed: int = 2) -> list[tuple[float, float, str]]:
    rng = random.Random(seed)
    return [(CENTRE[0] + rng.uniform(-0.5, 0.5), CENTRE[1] + rng.uniform(-0.5, 0.5), rng.choice(SEVERITIES))
            for _ in range(LOOKUPS)]


def scan(facilities: list[dict], lat: float, lng: float, severity: str) -> list[dict]:
    eligible = [f for f in facilities if severity in f["accepted_severity"]]
    return sorted(eligible, key=lambda f: haversine_km(lat, lng, f["lat"], f["lng"]))[:TOP_N]


def indexed(facilities: list[dict], lat: float, lng: float, severity: str) -> list[dict]:
    def distance(f: dict) -> float:
        return haversine_km(lat, lng, f["lat"], f["lng"])

    entries = cell_index.nearest(facilities, lat, lng, lambda f: severity in f["accepted_severity"], TOP_N, distance)
    pool = [f for f in facilities if severity in f["accepted_severity"]] if entries is None else [f for _, f in entries]
    return sorted(pool, key=distance)[:TOP_N]


def _mean_ms(lookup, facilities: list[dict], points: list[tuple[float, float, str]]) -> float:
    started = time.perf_counter()
    for lat, lng, severity in points:
        lookup(facilities, lat, lng, severity)
    return (time.perf_counter() - started) * 1000 / len(points)


def main() -> None:
    points = _points()
    print(f"{'facilities':>10}  {'scan ms':>9}  {'index ms':>9}  {'speedup':>8}")
    for count in (304, 10_000, 100_000):
        facilities = synthetic(count)
        indexed(facilities, *points[0])  # build the index outside the timing
        scan_ms = _mean_ms(scan, facilities, points)
        index_ms = _mean_ms(indexed, facilities, points)
        print(f"{count:>10}  {scan_ms:>9.3f}  {index_ms:>9.3f}  {scan_ms / index_ms:>7.1f}x")


if __name__ == "__main__":
    main()
```

Run it once (from `backend/`): `python -m scripts.perf_baseline.bench_lookup`
Expected: three rows. At 304 facilities both columns are the same (the list is below
`MIN_INDEXED`, so both are the scan); at 10,000 and 100,000 the index column stays under a
millisecond while the scan column grows with the facility count. Copy the printed table into
your checkpoint report.

- [ ] **Step 8: Run the whole backend suite and commit**

Run (from `backend/`): `doppler run -- pytest -q` — expected: no failure.

```bash
git add backend/requirements.txt backend/services/cell_index.py backend/services/proximity.py backend/tests/test_cell_index.py backend/scripts/perf_baseline/bench_lookup.py
git commit -m "feat(api): find candidate facilities through an h3 cell index"
```

---

### Task 11: Travel-time estimate and cache

**Files:**
- Create: `backend/services/travel_time.py`
- Test: `backend/tests/test_travel_time.py`

**Interfaces:**
- Consumes: `cell_index.cell_of` (task 10); `haversine_km`, `DRIVE_MPS`, `TRANSIT_MPS`,
  `WALK_MPS` from `services.proximity`.
- Produces:
  - `estimate_minutes(distance_km: float, mode: str) -> float` (`mode` is `car`, `bus`, `bike`
    or `walk`).
  - `remember(lat, lng, facility_id, mode, minutes, now=None) -> None`,
    `recall(lat, lng, facility_id, mode, now=None) -> float | None`.
  - `travel_minutes(lat, lng, facility: dict, mode, now=None) -> float`: remembered, else estimated.
  - `clear() -> None`; constants `MAX_ENTRIES = 20000`, `ENTRY_SECONDS = 900`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_travel_time.py`:

```python file=backend/tests/test_travel_time.py
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from services import travel_time

HERE = (43.6532, -79.3832)
SAME_CELL = (43.6533, -79.3833)   # about 14 m away
FAR_AWAY = (43.7000, -79.3000)
FACILITY = {"id": "f1", "lat": 43.6596, "lng": -79.3884}


@pytest.fixture(autouse=True)
def _clean():
    travel_time.clear()
    yield
    travel_time.clear()


def test_the_estimate_uses_one_speed_per_mode() -> None:
    assert travel_time.estimate_minutes(6.6, "car") == pytest.approx(10.0)
    assert travel_time.estimate_minutes(0.84, "walk") == pytest.approx(10.0)
    assert travel_time.estimate_minutes(3.6, "bus") == pytest.approx(10.0)
    assert travel_time.estimate_minutes(2.52, "bike") == pytest.approx(10.0)


def test_a_remembered_time_is_recalled_for_the_same_cell_facility_and_mode() -> None:
    travel_time.remember(*HERE, "f1", "car", 12, now=0)
    assert travel_time.recall(*SAME_CELL, "f1", "car", now=10) == 12
    assert travel_time.recall(*FAR_AWAY, "f1", "car", now=10) is None
    assert travel_time.recall(*HERE, "f2", "car", now=10) is None
    assert travel_time.recall(*HERE, "f1", "bike", now=10) is None


def test_a_remembered_time_expires() -> None:
    travel_time.remember(*HERE, "f1", "car", 12, now=0)
    assert travel_time.recall(*HERE, "f1", "car", now=travel_time.ENTRY_SECONDS) == 12
    assert travel_time.recall(*HERE, "f1", "car", now=travel_time.ENTRY_SECONDS + 1) is None


def test_travel_minutes_prefers_the_remembered_time_and_falls_back_to_the_estimate() -> None:
    estimate = travel_time.travel_minutes(*HERE, FACILITY, "car", now=0)
    assert 0 < estimate < 5
    travel_time.remember(*HERE, "f1", "car", 9, now=0)
    assert travel_time.travel_minutes(*HERE, FACILITY, "car", now=1) == 9


def test_the_oldest_entries_are_dropped_past_the_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(travel_time, "MAX_ENTRIES", 2)
    travel_time.remember(*HERE, "f1", "car", 1, now=0)
    travel_time.remember(*HERE, "f2", "car", 2, now=0)
    travel_time.remember(*HERE, "f3", "car", 3, now=0)
    assert travel_time.recall(*HERE, "f1", "car", now=0) is None
    assert travel_time.recall(*HERE, "f3", "car", now=0) == 3
```

- [ ] **Step 2: Run them and see them fail**

Run (from `backend/`): `doppler run -- pytest tests/test_travel_time.py -q`
Expected: collection error, `ImportError: cannot import name 'travel_time' from 'services'`.

- [ ] **Step 3: Write the module**

Create `backend/services/travel_time.py`:

```python file=backend/services/travel_time.py
"""How long it takes to reach a facility: a measured time when one is known, an estimate otherwise.

Measured times come from routes this process already asked Geoapify for. They are remembered
per origin cell (a few hundred metres across), facility and travel mode, for 15 minutes, in
process memory. They only improve the ranking of candidates: a drawn route always starts at the
guest's own position, so nothing remembered here is ever shown as someone's route.
"""
import time
from collections import OrderedDict

from services import cell_index
from services.proximity import DRIVE_MPS, TRANSIT_MPS, WALK_MPS, haversine_km

BIKE_MPS = 4.2
SPEED_MPS: dict[str, float] = {"car": DRIVE_MPS, "bus": TRANSIT_MPS, "bike": BIKE_MPS, "walk": WALK_MPS}

ORIGIN_RESOLUTION = 9
MAX_ENTRIES = 20000
ENTRY_SECONDS = 900

Key = tuple[str, str, str]  # (origin cell, facility id, travel mode)

_remembered: OrderedDict[Key, tuple[float, float]] = OrderedDict()  # key -> (minutes, stored at)


def estimate_minutes(distance_km: float, mode: str) -> float:
    return distance_km * 1000 / SPEED_MPS[mode] / 60


def _key(lat: float, lng: float, facility_id: object, mode: str) -> Key:
    return (cell_index.cell_of(lat, lng, ORIGIN_RESOLUTION), str(facility_id), mode)


def remember(lat: float, lng: float, facility_id: object, mode: str, minutes: float, now: float | None = None) -> None:
    key = _key(lat, lng, facility_id, mode)
    _remembered[key] = (float(minutes), time.monotonic() if now is None else now)
    _remembered.move_to_end(key)
    while len(_remembered) > MAX_ENTRIES:
        _remembered.popitem(last=False)


def recall(lat: float, lng: float, facility_id: object, mode: str, now: float | None = None) -> float | None:
    key = _key(lat, lng, facility_id, mode)
    entry = _remembered.get(key)
    if entry is None:
        return None
    minutes, stored_at = entry
    if (time.monotonic() if now is None else now) - stored_at > ENTRY_SECONDS:
        del _remembered[key]
        return None
    return minutes


def travel_minutes(lat: float, lng: float, facility: dict, mode: str, now: float | None = None) -> float:
    known = recall(lat, lng, facility["id"], mode, now)
    if known is not None:
        return known
    return estimate_minutes(haversine_km(lat, lng, facility["lat"], facility["lng"]), mode)


def clear() -> None:
    _remembered.clear()
```

- [ ] **Step 4: Run the tests and commit**

Run (from `backend/`): `doppler run -- pytest tests/test_travel_time.py -q` — expected: 5 passed.

```bash
git add backend/services/travel_time.py backend/tests/test_travel_time.py
git commit -m "feat(api): estimate travel time and remember measured times per origin cell"
```

---

### Task 12: Load counters shared through Redis

**Files:**
- Create: `backend/services/facility_load.py`
- Modify: `backend/config.py`, `backend/main.py` (`lifespan`)
- Test: `backend/tests/test_facility_load.py` (new), `backend/tests/test_config.py`

**Interfaces:**
- Consumes: `services.wait_times.redis_client`, `cell_index.cell_of`.
- Produces:
  - `config.load_aware_routing() -> bool` (`LOAD_AWARE_ROUTING`, on unless set to `0`, `off`,
    `false` or `no`).
  - `facility_load.record(facility: dict, severity: str, lat: float, lng: float) -> None`:
    counts one recommendation; does nothing when load-aware routing is off; never raises;
    never waits for Redis when called from the event loop.
  - `facility_load.recent_assignments(facility_id: str) -> int`: from the local copy.
  - `facility_load.refresh_once(now: float | None = None) -> dict[str, int]`,
    `facility_load.run_forever()` (coroutine), `facility_load.reset_for_tests()`,
    `facility_load.INSTANCE_ID`.
  - Redis keys: hash `load:{minute}` with field `{facility_id}|{instance_id}`; hash
    `spread:{minute}` with field `{cell}|{severity}|{category}`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_facility_load.py`:

```python file=backend/tests/test_facility_load.py
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import patch

import pytest

from services import facility_load

FACILITY = {"id": "f1", "category": "hospital", "lat": 43.6596, "lng": -79.3884}
HERE = (43.6532, -79.3832)
NOW = 600_000.0  # minute 10000


@pytest.fixture(autouse=True)
def _clean(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LOAD_AWARE_ROUTING", "on")
    monkeypatch.delenv("LOAD_WINDOW_MINUTES", raising=False)
    facility_load.reset_for_tests()
    yield
    facility_load.reset_for_tests()


def test_a_recommendation_is_counted_under_the_minute_the_facility_and_this_process() -> None:
    with patch("services.facility_load.redis_client") as redis_client, \
         patch("services.facility_load.time.time", return_value=NOW):
        facility_load.record(FACILITY, "routine", *HERE)

    pipe = redis_client.pipeline.return_value
    load_call, spread_call = pipe.hincrby.call_args_list
    assert load_call.args == ("load:10000", f"f1|{facility_load.INSTANCE_ID}", 1)
    key, field, amount = spread_call.args
    assert key == "spread:10000" and amount == 1
    assert field.endswith("|routine|hospital")
    assert [c.args for c in pipe.expire.call_args_list] == [("load:10000", 16 * 60), ("spread:10000", 86400)]
    assert pipe.execute.call_count == 1


def test_this_process_sees_its_own_choice_at_once() -> None:
    with patch("services.facility_load.redis_client"):
        facility_load.record(FACILITY, "routine", *HERE)
        facility_load.record(FACILITY, "routine", *HERE)
    assert facility_load.recent_assignments("f1") == 2
    assert facility_load.recent_assignments("other") == 0


def test_a_failed_write_is_swallowed() -> None:
    with patch("services.facility_load.redis_client") as redis_client:
        redis_client.pipeline.return_value.execute.side_effect = RuntimeError("redis down")
        facility_load.record(FACILITY, "routine", *HERE)  # must not raise
    assert facility_load.recent_assignments("f1") == 1


def test_nothing_is_counted_when_load_aware_routing_is_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOAD_AWARE_ROUTING", "off")
    with patch("services.facility_load.redis_client") as redis_client:
        facility_load.record(FACILITY, "routine", *HERE)
    redis_client.pipeline.assert_not_called()
    assert facility_load.recent_assignments("f1") == 0


def test_recording_from_the_event_loop_still_reaches_redis() -> None:
    with patch("services.facility_load.redis_client") as redis_client:
        async def turn() -> int:
            facility_load.record(FACILITY, "routine", *HERE)
            return facility_load.recent_assignments("f1")

        assert asyncio.run(turn()) == 1  # asyncio.run waits for the executor before returning
    assert redis_client.pipeline.return_value.execute.call_count == 1


def test_a_refresh_sums_the_window_across_processes() -> None:
    with patch("services.facility_load.redis_client") as redis_client, \
         patch("services.facility_load.time.time", return_value=NOW):
        pipe = redis_client.pipeline.return_value
        pipe.execute.return_value = [{}] * 13 + [{"f1|aaa": "2", "f2|aaa": "1"}, {"f1|bbb": "3"}]
        totals = facility_load.refresh_once()

    assert totals == {"f1": 5, "f2": 1}
    assert facility_load.recent_assignments("f1") == 5
    assert [c.args[0] for c in pipe.hgetall.call_args_list] == [f"load:{m}" for m in range(9986, 10001)]


def test_a_refresh_replaces_the_local_count() -> None:
    with patch("services.facility_load.redis_client") as redis_client:
        facility_load.record(FACILITY, "routine", *HERE)
        redis_client.pipeline.return_value.execute.return_value = [{}] * 15
        facility_load.refresh_once()
    assert facility_load.recent_assignments("f1") == 0


def test_a_failed_refresh_keeps_the_previous_counts() -> None:
    with patch("services.facility_load.redis_client") as redis_client:
        redis_client.pipeline.return_value.execute.return_value = [{"f1|aaa": "4"}] + [{}] * 14
        facility_load.refresh_once()
        redis_client.pipeline.return_value.execute.side_effect = RuntimeError("redis down")
        with pytest.raises(RuntimeError):
            facility_load.refresh_once()
    assert facility_load.recent_assignments("f1") == 4


def test_the_next_refresh_is_five_seconds_plus_up_to_twenty_percent() -> None:
    assert facility_load.next_delay(lambda: 0.0) == 5
    assert facility_load.next_delay(lambda: 1.0) == 6
```

In `backend/tests/test_config.py`, add at the end of the file:

```python


@pytest.mark.parametrize("raw, expected", [
    (None, True), ("on", True), ("true", True), ("1", True), ("anything", True),
    ("off", False), ("OFF", False), ("0", False), ("false", False), ("no", False), (" off ", False),
])
def test_load_aware_routing_is_on_unless_switched_off(monkeypatch: pytest.MonkeyPatch, raw, expected) -> None:
    import config

    if raw is None:
        monkeypatch.delenv("LOAD_AWARE_ROUTING", raising=False)
    else:
        monkeypatch.setenv("LOAD_AWARE_ROUTING", raw)
    assert config.load_aware_routing() is expected
```

(If `backend/tests/test_config.py` does not already `import pytest` at its top, add that import.)

- [ ] **Step 2: Run them and see them fail**

Run (from `backend/`): `doppler run -- pytest tests/test_facility_load.py tests/test_config.py -q`
Expected: `tests/test_facility_load.py` has a collection error
(`ImportError: cannot import name 'facility_load'`), and the new config test fails with
`AttributeError: module 'config' has no attribute 'load_aware_routing'`.

- [ ] **Step 3: Add the setting**

In `backend/config.py`, at the end of the file, add:

```python


def load_aware_routing() -> bool:
    """Whether a recommendation takes posted waits and recent assignments into account. On by
    default; "0", "off", "false" or "no" brings back nearest-first for every severity."""
    return os.environ.get("LOAD_AWARE_ROUTING", "on").strip().lower() not in ("0", "off", "false", "no")
```

- [ ] **Step 4: Write the counters**

Create `backend/services/facility_load.py`:

```python file=backend/services/facility_load.py
"""How many guests each facility was recently recommended to, shared by every API process.

Each recommendation increments one Redis hash field (minute, facility, this process). HINCRBY
is atomic, so processes need no lock and never wait for one another. Every process keeps a
local copy of the totals for the last LOAD_WINDOW_MINUTES, refreshed in the background, and the
recommendation score reads only that copy: Redis is never on the path of a request.

A second counter, by area, severity and facility category, is written for a later view of how
guests spread over the city. Nothing reads it yet.
"""
import asyncio
import logging
import random
import time
import uuid
from collections.abc import Callable

from starlette.concurrency import run_in_threadpool

from config import env_int, load_aware_routing
from services import cell_index
from services.wait_times import redis_client

logger = logging.getLogger(__name__)

INSTANCE_ID = uuid.uuid4().hex[:12]  # one field per process: the sum is the load, the fields show who wrote
REFRESH_SECONDS = 5
JITTER_FRACTION = 0.2
SPREAD_RESOLUTION = 7
SPREAD_EXPIRY_SECONDS = 86400

_recent: dict[str, int] = {}


def _window_minutes() -> int:
    return env_int("LOAD_WINDOW_MINUTES", 15, minimum=1, maximum=120)


def _current_minute(now: float | None = None) -> int:
    return int((time.time() if now is None else now) // 60)


def _write(facility_id: str, category: str, severity: str, lat: float, lng: float) -> None:
    minute = _current_minute()
    load_key, spread_key = f"load:{minute}", f"spread:{minute}"
    area = cell_index.cell_of(lat, lng, SPREAD_RESOLUTION)
    pipe = redis_client.pipeline()
    pipe.hincrby(load_key, f"{facility_id}|{INSTANCE_ID}", 1)
    pipe.expire(load_key, (_window_minutes() + 1) * 60)
    pipe.hincrby(spread_key, f"{area}|{severity}|{category}", 1)
    pipe.expire(spread_key, SPREAD_EXPIRY_SECONDS)
    pipe.execute()


def record(facility: dict, severity: str, lat: float, lng: float) -> None:
    """Counts one recommendation of `facility`. Never raises and, on the event loop, never
    waits for Redis: the write runs in the default executor."""
    if not load_aware_routing():
        return
    facility_id, category = str(facility["id"]), str(facility.get("category"))
    _recent[facility_id] = _recent.get(facility_id, 0) + 1  # visible here before the next refresh

    def write() -> None:
        try:
            _write(facility_id, category, severity, lat, lng)
        except Exception as exc:
            logger.warning("facility_load_write_failed", extra={"error_type": type(exc).__name__})

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:  # called from synchronous code (a script, a test)
        write()
        return
    loop.run_in_executor(None, write)


def recent_assignments(facility_id: str) -> int:
    return _recent.get(str(facility_id), 0)


def refresh_once(now: float | None = None) -> dict[str, int]:
    """Blocking. Replaces the local copy with the sum over the window, across all processes.
    A Redis failure propagates and leaves the previous copy in place."""
    global _recent
    minute = _current_minute(now)
    pipe = redis_client.pipeline()
    for past in range(minute - _window_minutes() + 1, minute + 1):
        pipe.hgetall(f"load:{past}")
    totals: dict[str, int] = {}
    for fields in pipe.execute():
        for field, count in (fields or {}).items():
            facility_id = str(field).split("|", 1)[0]
            totals[facility_id] = totals.get(facility_id, 0) + int(count)
    _recent = totals
    return totals


def next_delay(rng: Callable[[], float] = random.random) -> float:
    return REFRESH_SECONDS * (1 + JITTER_FRACTION * rng())


async def run_forever() -> None:
    """The background refresh. Started once by the app's lifespan and cancelled at shutdown."""
    while True:
        await asyncio.sleep(next_delay())
        if not load_aware_routing():
            continue
        try:
            await run_in_threadpool(refresh_once)
        except Exception as exc:
            logger.warning("facility_load_refresh_failed", extra={"error_type": type(exc).__name__})


def reset_for_tests() -> None:
    global _recent
    _recent = {}
```

- [ ] **Step 5: Start the refresh with the app**

In `backend/main.py`:

(a) Replace `from services import facility_bytes, wait_cache` with
`from services import facility_bytes, facility_load, wait_cache`.

(b) In `lifespan`, replace

```python
    background_tasks = [asyncio.create_task(wait_cache.run_forever())]
```

with:

```python
    background_tasks = [
        asyncio.create_task(wait_cache.run_forever()),
        asyncio.create_task(facility_load.run_forever()),
    ]
```

- [ ] **Step 6: Run the tests and commit**

Run (from `backend/`): `doppler run -- pytest tests/test_facility_load.py tests/test_config.py -q`
Expected: all pass.
Run (from `backend/`): `doppler run -- pytest -q` — expected: no failure.

```bash
git add backend/services/facility_load.py backend/config.py backend/main.py backend/tests/test_facility_load.py backend/tests/test_config.py
git commit -m "feat(api): count recent recommendations per facility in redis without locks"
```

---

### Task 13: The load-aware choice

**Files:**
- Create: `backend/services/recommendation.py`, `backend/tests/conftest.py`
- Modify: `backend/services/llm_agent.py` (`_handle_triage`),
  `backend/scripts/symptom_eval/system_under_test.py`
- Test: `backend/tests/test_recommendation.py` (new),
  `backend/tests/llm/test_agent_recommendation.py` (new)

**Interfaces:**
- Consumes: `travel_time.travel_minutes` (task 11), `facility_load.recent_assignments` and
  `facility_load.record` (task 12), `current_wait()` (task 2), `config.load_aware_routing()`.
- Produces:
  - `recommendation.rank_facilities(candidates: list[dict], severity: str, lat: float, lng: float, rng=random.random) -> list[dict]`:
    the recommended facility first, then the others by score. For `urgent` and `emergent`, with
    load-aware routing off, or with fewer than two candidates, it returns `candidates` unchanged
    (nearest first).
  - `recommendation.score_minutes(facility, lat, lng, wait_map) -> float`.
  - The agent recommends `rank_facilities(...)[0]` and counts it with `facility_load.record`.

- [ ] **Step 1: Keep the other tests deterministic**

Load-aware routing picks at random among close candidates and writes to Redis. Every existing
test expects nearest-first. Create `backend/tests/conftest.py`:

```python
import pytest


@pytest.fixture(autouse=True)
def _nearest_first_recommendations(monkeypatch: pytest.MonkeyPatch) -> None:
    """Load-aware routing chooses at random among close candidates and writes counters to
    Redis. Tests get nearest-first, with no Redis write, unless they switch it on themselves."""
    monkeypatch.setenv("LOAD_AWARE_ROUTING", "off")
```

The evaluation harness must stay deterministic too. In
`backend/scripts/symptom_eval/system_under_test.py`, in `LiveLLMAgentAdapter.__init__`, directly
below the line `os.environ["GRAPH_RAG_PROVIDER"] = graph_rag_provider`, add:

```python
        # Evaluation runs compare severity and wording across runs: no random pick among close
        # facilities, and no load counters written to the shared Redis.
        os.environ["LOAD_AWARE_ROUTING"] = "off"
```

- [ ] **Step 2: Write the failing tests**

Create `backend/tests/test_recommendation.py`:

```python file=backend/tests/test_recommendation.py
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import patch

import pytest

from services import facility_load, travel_time
from services.recommendation import rank_facilities, score_minutes
from services.wait_cache import WaitSnapshot

HERE = (43.6532, -79.3832)
# NEAR is about 0.8 km away, MID about 3.3 km, FAR about 7.7 km: 1.2, 5.0 and 11.7 minutes by car.
NEAR = {"id": "near", "name": "Near", "category": "hospital", "lat": 43.6596, "lng": -79.3884, "distanceKm": 0.82}
MID = {"id": "mid", "name": "Mid", "category": "ambulatory", "lat": 43.6800, "lng": -79.4000, "distanceKm": 3.27}
FAR = {"id": "far", "name": "Far", "category": "hospital", "lat": 43.7224, "lng": -79.3763, "distanceKm": 7.71}


def _wait(**minutes: int) -> WaitSnapshot:
    wait_map = {fid: {"wait_minutes": m, "raw_wait": None, "predicted": False} for fid, m in minutes.items()}
    return WaitSnapshot(wait_map, "v", None)


@pytest.fixture(autouse=True)
def _on(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LOAD_AWARE_ROUTING", "on")
    monkeypatch.setenv("LOAD_SCORE_TIE_MINUTES", "0")
    travel_time.clear()
    facility_load.reset_for_tests()
    yield
    travel_time.clear()
    facility_load.reset_for_tests()


def _rank(candidates: list[dict], severity: str, wait: WaitSnapshot = _wait(), rng=lambda: 0.0) -> list[str]:
    with patch("services.recommendation.current_wait", return_value=wait):
        return [f["id"] for f in rank_facilities(candidates, severity, *HERE, rng=rng)]


def test_with_nothing_else_known_the_nearest_is_recommended() -> None:
    assert _rank([NEAR, MID, FAR], "routine") == ["near", "mid", "far"]


def test_a_long_posted_wait_moves_the_recommendation() -> None:
    assert _rank([NEAR, MID, FAR], "moderate", _wait(near=60, mid=5)) == ["mid", "far", "near"]


def test_a_facility_without_wait_data_counts_as_no_wait() -> None:
    assert _rank([NEAR, MID], "routine", _wait(mid=0)) == ["near", "mid"]


def test_recent_assignments_move_the_recommendation() -> None:
    with patch("services.recommendation.facility_load.recent_assignments",
               side_effect=lambda fid: 10 if fid == "near" else 0):
        assert _rank([NEAR, MID, FAR], "routine") == ["mid", "far", "near"]


def test_a_remembered_road_time_replaces_the_estimate() -> None:
    travel_time.remember(*HERE, "near", "car", 30)
    assert _rank([NEAR, MID], "routine") == ["mid", "near"]


@pytest.mark.parametrize("severity", ["urgent", "emergent"])
def test_urgent_and_emergent_ignore_waits_and_load(severity: str) -> None:
    with patch("services.recommendation.facility_load.recent_assignments", return_value=50):
        assert _rank([NEAR, MID, FAR], severity, _wait(near=600)) == ["near", "mid", "far"]


def test_switched_off_it_is_nearest_first(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOAD_AWARE_ROUTING", "off")
    assert _rank([NEAR, MID, FAR], "routine", _wait(near=600)) == ["near", "mid", "far"]


def test_close_scores_are_a_tie_and_the_pick_among_them_is_random(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOAD_SCORE_TIE_MINUTES", "5")
    assert _rank([NEAR, MID, FAR], "routine", rng=lambda: 0.0) == ["near", "mid", "far"]
    assert _rank([NEAR, MID, FAR], "routine", rng=lambda: 0.99) == ["mid", "near", "far"]


def test_a_candidate_outside_the_tie_band_is_never_picked(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOAD_SCORE_TIE_MINUTES", "5")
    for value in (0.0, 0.34, 0.67, 0.999):
        assert _rank([NEAR, MID, FAR], "routine", rng=lambda v=value: v)[0] != "far"


def test_one_candidate_or_none_is_returned_as_is() -> None:
    assert _rank([NEAR], "routine") == ["near"]
    assert _rank([], "routine") == []


def test_the_score_is_travel_plus_wait_plus_the_load_penalty() -> None:
    wait_map = {"mid": {"wait_minutes": 20}}
    with patch("services.recommendation.facility_load.recent_assignments", return_value=3):
        score = score_minutes(MID, *HERE, wait_map)
    travel = travel_time.travel_minutes(*HERE, MID, "car")
    assert score == pytest.approx(travel + 20 + 3 * 4.0)  # 4 minutes per recent guest for "ambulatory"
```

Create `backend/tests/llm/test_agent_recommendation.py`:

```python file=backend/tests/llm/test_agent_recommendation.py
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from unittest.mock import AsyncMock, MagicMock, patch

from services.llm_agent import LLMAgent

HERE = (43.6532, -79.3832)
A = {"id": "a", "name": "Alpha Clinic", "category": "ambulatory", "address": "1 Main St",
     "lat": 43.6596, "lng": -79.3884, "distanceKm": 0.8}
B = {"id": "b", "name": "Beta Clinic", "category": "ambulatory", "address": "2 Main St",
     "lat": 43.6800, "lng": -79.4000, "distanceKm": 3.3}
HISTORY = [
    {"role": "user", "content": "I have a sore throat"},
    {"role": "assistant", "content": "Since when?"},
    {"role": "user", "content": "Two days"},
    {"role": "assistant", "content": "Any fever?"},
    {"role": "user", "content": "A mild one"},
    {"role": "assistant", "content": "Trouble swallowing?"},
]


def _client(severity: str) -> MagicMock:
    classification = MagicMock(content=None, tool_calls=[{
        "id": "tc1", "name": "triage_response",
        "arguments": json.dumps({"severity": severity, "reasoning": "r", "information_sufficient": True}),
    }])
    answer = MagicMock(content="Please go to Beta Clinic.", tool_calls=None)
    client = MagicMock()
    client.chat = AsyncMock(side_effect=[classification, answer])
    return client


def test_the_agent_recommends_the_ranked_first_facility_and_counts_it() -> None:
    with patch("services.llm_agent.find_nearest_facilities", return_value=[A, B]), \
         patch("services.llm_agent.rank_facilities", return_value=[B, A]) as rank, \
         patch("services.llm_agent.facility_load.record") as record:
        result = asyncio.run(LLMAgent(client=_client("moderate")).respond("No", HISTORY, lat=HERE[0], lng=HERE[1]))

    assert result["turn_type"] == "triage"
    assert result["recommended_facility"] == B and result["nearby_facilities"] == [A]
    rank.assert_called_once_with([A, B], "moderate", HERE[0], HERE[1])
    record.assert_called_once_with(B, "moderate", HERE[0], HERE[1])


def test_without_a_location_nothing_is_ranked_or_counted() -> None:
    with patch("services.llm_agent.find_nearest_facilities") as find, \
         patch("services.llm_agent.rank_facilities") as rank, \
         patch("services.llm_agent.facility_load.record") as record:
        result = asyncio.run(LLMAgent(client=_client("moderate")).respond("No", HISTORY))

    assert result["recommended_facility"] is None
    find.assert_not_called()
    rank.assert_not_called()
    record.assert_not_called()
```

- [ ] **Step 3: Run them and see them fail**

Run (from `backend/`):
`doppler run -- pytest tests/test_recommendation.py tests/llm/test_agent_recommendation.py -q`
Expected: `tests/test_recommendation.py` has a collection error
(`ModuleNotFoundError: No module named 'services.recommendation'`);
`tests/llm/test_agent_recommendation.py` fails with
`AttributeError: <module 'services.llm_agent'> does not have the attribute 'rank_facilities'`.

- [ ] **Step 4: Write the choice**

Create `backend/services/recommendation.py`:

```python file=backend/services/recommendation.py
"""Which candidate facility to recommend.

Nearest-first sends everyone in an area to the same place, and the posted wait it would follow
is up to 15 minutes old. For routine and moderate cases the choice therefore scores each
candidate in minutes: travel time, plus the posted wait, plus a penalty for each guest recently
sent there. Candidates whose scores are close are a tie, and the pick among them is random, so
guests arriving together are not all given the same answer.

Urgent and emergent cases are never balanced: they get the nearest appropriate facility.
"""
import random
from collections.abc import Callable

from config import env_int, load_aware_routing
from services import facility_load, travel_time
from services.wait_cache import current_wait

BALANCED_SEVERITIES = ("routine", "moderate")
RANKING_MODE = "car"  # the travel mode is not known when the recommendation is made
# Minutes added per guest recently sent to a facility, by category. A starting value: there is
# no capacity data yet, and a hospital absorbs an extra arrival better than a small clinic.
LOAD_PENALTY_MINUTES: dict[str, float] = {"hospital": 2.0, "ambulatory": 4.0, "residential": 4.0}
DEFAULT_PENALTY_MINUTES = 3.0


def score_minutes(facility: dict, lat: float, lng: float, wait_map: dict[str, dict]) -> float:
    facility_id = str(facility["id"])
    travel = travel_time.travel_minutes(lat, lng, facility, RANKING_MODE)
    wait = (wait_map.get(facility_id) or {}).get("wait_minutes") or 0
    penalty = LOAD_PENALTY_MINUTES.get(str(facility.get("category")), DEFAULT_PENALTY_MINUTES)
    return travel + wait + facility_load.recent_assignments(facility_id) * penalty


def rank_facilities(
    candidates: list[dict],
    severity: str,
    lat: float,
    lng: float,
    rng: Callable[[], float] = random.random,
) -> list[dict]:
    """The recommended facility first, then the others by score. `candidates` is nearest first
    and is returned unchanged when the choice is not balanced."""
    if len(candidates) < 2 or severity not in BALANCED_SEVERITIES or not load_aware_routing():
        return candidates

    wait_map = current_wait().wait_map
    scored = sorted(
        ((score_minutes(facility, lat, lng, wait_map), position, facility)
         for position, facility in enumerate(candidates)),
        key=lambda item: (item[0], item[1]),
    )
    tie_minutes = env_int("LOAD_SCORE_TIE_MINUTES", 5, minimum=0, maximum=120)
    tied = [item for item in scored if item[0] - scored[0][0] <= tie_minutes]
    chosen = tied[min(int(rng() * len(tied)), len(tied) - 1)]
    return [chosen[2]] + [item[2] for item in scored if item is not chosen]
```

- [ ] **Step 5: Use it in the agent**

In `backend/services/llm_agent.py`:

(a) Replace the line `from services.proximity import find_nearest_facilities` with:

```python
from services import facility_load
from services.proximity import find_nearest_facilities
from services.recommendation import rank_facilities
```

(b) In `_handle_triage`, replace

```python
        if needs_location:
            facilities = find_nearest_facilities(lat=lat, lng=lng, severity=severity)
            if facilities:
                recommended_facility = facilities[0]
                nearby_facilities = facilities[1:]
```

with:

```python
        if needs_location:
            facilities = find_nearest_facilities(lat=lat, lng=lng, severity=severity)
            if facilities:
                # Nearest first for urgent and emergent; balanced by wait and load otherwise.
                ranked = rank_facilities(facilities, severity, lat, lng)
                recommended_facility = ranked[0]
                nearby_facilities = ranked[1:]
                facility_load.record(recommended_facility, severity, lat, lng)
```

- [ ] **Step 6: Run the tests and commit**

Run (from `backend/`):
`doppler run -- pytest tests/test_recommendation.py tests/llm -q` — expected: all pass.
Run (from `backend/`): `doppler run -- pytest -q` — expected: no failure.

```bash
git add backend/services/recommendation.py backend/services/llm_agent.py backend/scripts/symptom_eval/system_under_test.py backend/tests/conftest.py backend/tests/test_recommendation.py backend/tests/llm/test_agent_recommendation.py
git commit -m "feat(agent): choose the recommended facility by travel time, posted wait and recent load"
```

---

### Task 14: A Geoapify budget, and an estimated answer when it is spent

**Files:**
- Create: `backend/services/geoapify_limiter.py`
- Modify: `backend/services/routing.py`, `backend/routers/routes.py` (replaced),
  `backend/models.py`, `backend/metrics.py`, `shared/types.ts`
- Test: `backend/tests/test_geoapify_limiter.py` (new), `backend/tests/test_routing_budget.py`
  (new), `backend/tests/test_routes_router.py`

**Interfaces:**
- Consumes: `travel_time.estimate_minutes`, `travel_time.remember` (task 11).
- Produces:
  - `geoapify_limiter.take(count: int, priority: bool, now: float | None = None) -> bool`,
    `geoapify_limiter.reset_for_tests()`.
  - `routing.routing_url() -> str` (honours `GEOAPIFY_BASE_URL`),
    `routing.estimated_route(origin: dict, facility: dict, mode: str) -> dict`.
  - `RoutesRequest.severity: Severity | None = None`; `CandidateRoute.estimated: bool = False`.
  - Metric `routes_degraded_total`.
  - `shared/types.ts`: `RoutesRequest.severity?`, `CandidateRoute.estimated?`,
    `RouteResult.estimated?`.

`severity` comes from the client, so a guest could claim `emergent` to skip the budget. The
per-guest route limit (60 per 10 minutes) already bounds that, and the alternative, refusing a
real emergency, is worse.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_geoapify_limiter.py`:

```python file=backend/tests/test_geoapify_limiter.py
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from services import geoapify_limiter


@pytest.fixture(autouse=True)
def _clean(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GEOAPIFY_RATE_PER_SECOND", "5")
    geoapify_limiter.reset_for_tests()
    yield
    geoapify_limiter.reset_for_tests()


def test_it_starts_full_and_refuses_when_empty() -> None:
    assert geoapify_limiter.take(3, priority=False, now=0.0)
    assert geoapify_limiter.take(2, priority=False, now=0.0)
    assert not geoapify_limiter.take(1, priority=False, now=0.0)


def test_a_request_larger_than_what_is_left_is_refused_whole() -> None:
    assert geoapify_limiter.take(4, priority=False, now=0.0)
    assert not geoapify_limiter.take(2, priority=False, now=0.0)
    assert geoapify_limiter.take(1, priority=False, now=0.0)


def test_it_refills_at_the_rate_and_never_above_it() -> None:
    assert geoapify_limiter.take(5, priority=False, now=0.0)
    assert not geoapify_limiter.take(1, priority=False, now=0.1)
    assert geoapify_limiter.take(1, priority=False, now=0.3)   # 0.3 s at 5 per second is 1.5 tokens
    assert geoapify_limiter.take(5, priority=False, now=100.0)
    assert not geoapify_limiter.take(1, priority=False, now=100.0)


def test_priority_is_never_refused_and_is_paid_back_by_the_others() -> None:
    assert geoapify_limiter.take(5, priority=False, now=0.0)
    assert geoapify_limiter.take(3, priority=True, now=0.0)
    assert not geoapify_limiter.take(1, priority=False, now=0.5)  # 2.5 refilled, still below zero
    assert geoapify_limiter.take(1, priority=False, now=1.0)


def test_the_debt_of_priority_requests_is_bounded() -> None:
    for _ in range(100):
        assert geoapify_limiter.take(3, priority=True, now=0.0)
    assert geoapify_limiter.take(1, priority=False, now=2.5)  # at most one second of debt
```

Create `backend/tests/test_routing_budget.py`:

```python file=backend/tests/test_routing_budget.py
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx
import pytest

from services import routing

ORIGIN = {"lat": 43.6532, "lng": -79.3832}
A = {"id": "a", "lat": 43.6596, "lng": -79.3884}
PAYLOAD = {"features": [{
    "properties": {"time": 600, "distance": 4200},
    "geometry": {"type": "LineString", "coordinates": [[-79.38, 43.65], [-79.39, 43.66]]},
}]}


def _called_paths(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    monkeypatch.setenv("GEOAPIFY_API_KEY", "k")
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(f"{request.url.scheme}://{request.url.host}:{request.url.port}{request.url.path}")
        return httpx.Response(200, json=PAYLOAD)

    routes = asyncio.run(routing.routes_for(ORIGIN, [A], "car", transport=httpx.MockTransport(handler)))
    assert routes[0]["eta_minutes"] == 10
    return seen


def test_the_base_url_setting_moves_the_routing_call(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEOAPIFY_BASE_URL", "http://mock:9000/")
    assert _called_paths(monkeypatch) == ["http://mock:9000/v1/routing"]


def test_without_the_setting_the_call_goes_to_geoapify(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GEOAPIFY_BASE_URL", raising=False)
    assert _called_paths(monkeypatch) == ["https://api.geoapify.com:None/v1/routing"]


def test_an_estimated_route_has_a_time_and_a_distance_and_no_road_shape() -> None:
    route = routing.estimated_route(ORIGIN, A, "walk")
    assert route["facility_id"] == "a" and route["estimated"] is True and route["geometry"] is None
    assert route["distance_km"] == 0.8
    assert route["eta_minutes"] == 10  # 0.82 km at walking speed


def test_an_estimate_is_never_zero_minutes() -> None:
    next_door = {"id": "n", "lat": ORIGIN["lat"], "lng": ORIGIN["lng"]}
    assert routing.estimated_route(ORIGIN, next_door, "car")["eta_minutes"] == 1
```

In `backend/tests/test_routes_router.py`:

(a) Replace the import line `from services import routing` with:

```python
from services import geoapify_limiter, routing, travel_time
```

(b) Replace the `_defaults` fixture with:

```python
@pytest.fixture(autouse=True)
def _defaults(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.delenv("GEOAPIFY_RATE_PER_SECOND", raising=False)
    geoapify_limiter.reset_for_tests()
    travel_time.clear()
    with patch.object(routes, "get_cached_facilities", return_value=(FACILITIES, '"etag"')), \
         patch.object(routes, "check_rate_limit", return_value=None) as limiter:
        yield limiter
    geoapify_limiter.reset_for_tests()
    travel_time.clear()
```

(c) Add at the end of the file:

```python


def _spend_the_budget() -> None:
    while geoapify_limiter.take(1, priority=False):
        pass


def test_a_routine_request_gets_an_estimate_when_the_budget_is_spent() -> None:
    _spend_the_budget()
    fake = AsyncMock()
    with patch.object(routes.routing, "routes_for", fake):
        resp = _client().post("/routes", json={**BODY, "severity": "routine"})

    assert resp.status_code == 200
    body = resp.json()
    assert [r["estimated"] for r in body["routes"]] == [True, True]
    assert all(r["geometry"] is None and r["eta_minutes"] >= 1 for r in body["routes"])
    assert body["fastest_facility_id"] == "a"  # the nearer of the two
    fake.assert_not_called()


def test_a_request_without_a_severity_is_not_a_priority() -> None:
    _spend_the_budget()
    fake = AsyncMock()
    with patch.object(routes.routing, "routes_for", fake):
        resp = _client().post("/routes", json=BODY)
    assert resp.json()["routes"][0]["estimated"] is True
    fake.assert_not_called()


@pytest.mark.parametrize("severity", ["urgent", "emergent"])
def test_urgent_and_emergent_are_routed_even_when_the_budget_is_spent(severity: str) -> None:
    _spend_the_budget()
    fake = AsyncMock(return_value=[_found("a", 20), _found("b", 9)])
    with patch.object(routes.routing, "routes_for", fake):
        resp = _client().post("/routes", json={**BODY, "severity": severity})

    assert resp.status_code == 200
    assert [r["estimated"] for r in resp.json()["routes"]] == [False, False]
    fake.assert_awaited_once()


def test_a_drawn_route_is_not_marked_estimated_and_its_time_is_remembered() -> None:
    with patch.object(routes.routing, "routes_for", AsyncMock(return_value=[_found("a", 20), _missing("b")])):
        body = _client().post("/routes", json=BODY).json()

    assert body["routes"][0]["estimated"] is False
    origin = BODY["origin"]
    assert travel_time.recall(origin["lat"], origin["lng"], "a", "bike") == 20
    assert travel_time.recall(origin["lat"], origin["lng"], "b", "bike") is None


def test_an_unknown_severity_is_422() -> None:
    assert _client().post("/routes", json={**BODY, "severity": "critical"}).status_code == 422
```

- [ ] **Step 2: Run them and see them fail**

Run (from `backend/`):
`doppler run -- pytest tests/test_geoapify_limiter.py tests/test_routing_budget.py tests/test_routes_router.py -q`
Expected: collection errors, `ImportError: cannot import name 'geoapify_limiter' from 'services'`.

- [ ] **Step 3: Write the limiter**

Create `backend/services/geoapify_limiter.py`:

```python file=backend/services/geoapify_limiter.py
"""A token bucket in front of Geoapify, in this process.

Geoapify's plan sets a number of requests per second, and that, not this server, is the ceiling
on drawn routes. The bucket holds one second of the plan's rate. A request for an urgent or
emergent case is never refused: it takes its tokens even when none are left, and the debt is
paid back by the requests that follow. The debt is bounded at one second of the rate.

GEOAPIFY_RATE_PER_SECOND is per process: with several API processes, set it to the plan's rate
divided by their number.
"""
import time

from config import env_int

_tokens: float | None = None  # None until the first request: the bucket starts full
_stamp = 0.0


def take(count: int, priority: bool, now: float | None = None) -> bool:
    """Takes `count` tokens (one per Geoapify call). False when a non-priority request cannot
    have them all; nothing is taken then."""
    global _tokens, _stamp
    now = time.monotonic() if now is None else now
    capacity = float(env_int("GEOAPIFY_RATE_PER_SECOND", 5, minimum=1, maximum=1000))
    if _tokens is None:
        _tokens = capacity
    else:
        _tokens = min(capacity, _tokens + (now - _stamp) * capacity)
    _stamp = now

    if priority or _tokens >= count:
        _tokens = max(_tokens - count, -capacity)
        return True
    return False


def reset_for_tests() -> None:
    global _tokens, _stamp
    _tokens, _stamp = None, 0.0
```

Run (from `backend/`): `doppler run -- pytest tests/test_geoapify_limiter.py -q` — expected: 5 passed.

- [ ] **Step 4: Change `backend/services/routing.py`**

(a) Replace the two import lines

```python
from metrics import ROUTING_CALL_DURATION, timed
```

with:

```python
from metrics import ROUTING_CALL_DURATION, timed
from services import travel_time
from services.proximity import haversine_km
```

(b) Replace the line `GEOAPIFY_ROUTING_URL = "https://api.geoapify.com/v1/routing"` with:

```python
GEOAPIFY_DEFAULT_BASE_URL = "https://api.geoapify.com"


def routing_url() -> str:
    """The Routing endpoint. GEOAPIFY_BASE_URL exists so a load test can point the API at a
    mock; it is set on the staging service only, never for guests."""
    base = os.environ.get("GEOAPIFY_BASE_URL", "").strip() or GEOAPIFY_DEFAULT_BASE_URL
    return base.rstrip("/") + "/v1/routing"
```

(c) In `_fetch_route`, replace

```python
            response = await client.get(GEOAPIFY_ROUTING_URL, params=params)
```

with:

```python
            response = await client.get(routing_url(), params=params)
```

(d) Directly above the function `fastest_facility_id`, add:

```python
def estimated_route(origin: dict[str, float], facility: dict, mode: str) -> dict:
    """A candidate answered without calling Geoapify: straight-line distance, a time estimated
    from it, and no road shape. Used when the Geoapify budget is spent."""
    distance_km = haversine_km(origin["lat"], origin["lng"], facility["lat"], facility["lng"])
    return {
        "facility_id": str(facility["id"]),
        "eta_minutes": max(1, round(travel_time.estimate_minutes(distance_km, mode))),
        "distance_km": round(distance_km, 1),
        "geometry": None,
        "estimated": True,
    }


```

- [ ] **Step 5: Add the model fields and the metric**

(a) `backend/models.py`, in `class RoutesRequest`, directly below the line
`    mode:         TravelMode`, add:

```python
    severity:     Severity | None = None  # lets urgent and emergent cases skip the Geoapify budget
```

(b) `backend/models.py`, in `class CandidateRoute`, directly below the line
`    geometry:    list[tuple[float, float]] | None = None`, add:

```python
    estimated:   bool = False  # True: no Geoapify call was made; time and distance are estimates
```

(c) `backend/metrics.py`, directly below the definition of `ROUTING_CALL_DURATION`, add:

```python
ROUTES_DEGRADED = Counter(
    "routes_degraded_total", "Route requests answered with estimates because the Geoapify budget was spent",
    registry=_registry,
)
```

- [ ] **Step 6: Replace `backend/routers/routes.py`**

```python
"""POST /routes: travel routes from the caller's position to up to three candidate facilities."""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

import config
from cache import get_cached_facilities
from metrics import ROUTES_DEGRADED
from middleware.auth import get_actor
from models import RoutesRequest, RoutesResponse
from services import geoapify_limiter, routing, travel_time
from services.rate_limit import busy_response, check_rate_limit, client_ip

router = APIRouter(tags=["routes"])

PRIORITY_SEVERITIES = ("urgent", "emergent")


@router.post("/routes", response_model=RoutesResponse)
async def post_routes(
    body: RoutesRequest, request: Request, actor: object = Depends(get_actor)
) -> RoutesResponse | JSONResponse:
    if body.mode not in config.modes_enabled():
        raise HTTPException(422, "Travel mode not enabled")

    if getattr(actor, "is_guest", False):
        retry_after = await run_in_threadpool(
            check_rate_limit,
            str(actor.id),  # type: ignore[attr-defined]
            client_ip(request),
            bucket="routes",
        )
        if retry_after is not None:
            return busy_response(retry_after)

    cached, _ = get_cached_facilities()
    if not cached:
        raise HTTPException(503, "Facilities unavailable")
    # The request carries ids only: coordinates come from our own list, so this endpoint cannot be
    # used to route between arbitrary points on our Geoapify quota.
    by_id = {str(facility["id"]): facility for facility in cached}
    if any(facility_id not in by_id for facility_id in body.facility_ids):
        raise HTTPException(404, "Unknown facility")
    candidates = [by_id[facility_id] for facility_id in body.facility_ids]
    origin = body.origin.model_dump()

    # One Geoapify call per candidate. An urgent or emergent case always gets its calls; the
    # others get an estimate, with no road shape, once the plan's rate is used up.
    priority = body.severity is not None and body.severity.value in PRIORITY_SEVERITIES
    if geoapify_limiter.take(len(candidates), priority):
        try:
            routes = await routing.routes_for(origin, candidates, body.mode)
        except routing.RoutingNotConfigured as exc:
            raise HTTPException(503, "Routing unavailable") from exc
        for route in routes:
            if route["eta_minutes"] is not None:
                travel_time.remember(origin["lat"], origin["lng"], route["facility_id"], body.mode, route["eta_minutes"])
    else:
        ROUTES_DEGRADED.inc()
        routes = [routing.estimated_route(origin, facility, body.mode) for facility in candidates]

    fastest = routing.fastest_facility_id(routes)
    if fastest is None:
        raise HTTPException(502, "No route found")
    return RoutesResponse(mode=body.mode, routes=routes, fastest_facility_id=fastest)
```

- [ ] **Step 7: Add the fields to the shared types**

In `shared/types.ts`:

(a) In `export interface RoutesRequest`, below the line `  mode:         TravelModeKey`, add:

```ts
  severity?:    Severity      // lets urgent and emergent cases skip the Geoapify budget
```

(b) In `export interface CandidateRoute`, below the `geometry:` line, add:

```ts
  estimated?:  boolean                   // true: no road route, time and distance are estimates
```

(c) In `export interface RouteResult`, below the `geometry:` line, add:

```ts
  estimated?:  boolean
```

- [ ] **Step 8: Run the tests and commit**

Run (from `backend/`):
`doppler run -- pytest tests/test_geoapify_limiter.py tests/test_routing_budget.py tests/test_routes_router.py tests/test_routing.py -q`
Expected: all pass.
Run (from `backend/`): `doppler run -- pytest -q` — expected: no failure.
Run (from `webapp/`): `npx tsc -b` — expected: no error.

```bash
git add backend/services/geoapify_limiter.py backend/services/routing.py backend/routers/routes.py backend/models.py backend/metrics.py shared/types.ts backend/tests/test_geoapify_limiter.py backend/tests/test_routing_budget.py backend/tests/test_routes_router.py
git commit -m "feat(routes): keep geoapify calls within the plan rate and answer with an estimate past it"
```

---

### Task 15: Settings exposed to the client, the stub warning, and the API document

**Files:**
- Modify: `backend/config.py`, `backend/models.py`, `backend/routers/demo.py`,
  `backend/main.py`, `shared/types.ts`, `webapp/src/lib/config.ts`, `docs/API.md`
- Test: `backend/tests/test_config.py`, `backend/tests/test_demo_router.py`,
  `backend/tests/test_health.py`

**Interfaces:**
- Produces:
  - `config.routes_up_front() -> int` (`ROUTES_UP_FRONT`, default 1, 1 to 3).
  - `config.stubbed_providers() -> list[str]`: which of `GROQ_BASE_URL`, `GEOAPIFY_BASE_URL`
    are set.
  - `GET /config` returns `routes_up_front`. `GET /health` returns `"stubbed": true` when a
    base-URL override is set, and the API logs a warning at startup.
  - `AppConfig.routes_up_front?: number` in `shared/types.ts`.

- [ ] **Step 1: Write the failing tests**

(a) In `backend/tests/test_config.py`, add at the end of the file:

```python


def test_one_route_is_requested_up_front_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    import config

    monkeypatch.delenv("ROUTES_UP_FRONT", raising=False)
    assert config.routes_up_front() == 1
    monkeypatch.setenv("ROUTES_UP_FRONT", "3")
    assert config.routes_up_front() == 3
    monkeypatch.setenv("ROUTES_UP_FRONT", "9")
    assert config.routes_up_front() == 1


def test_stubbed_providers_lists_the_overrides_that_are_set(monkeypatch: pytest.MonkeyPatch) -> None:
    import config

    monkeypatch.delenv("GROQ_BASE_URL", raising=False)
    monkeypatch.delenv("GEOAPIFY_BASE_URL", raising=False)
    assert config.stubbed_providers() == []
    monkeypatch.setenv("GEOAPIFY_BASE_URL", "http://mock:9000")
    assert config.stubbed_providers() == ["geoapify"]
    monkeypatch.setenv("GROQ_BASE_URL", "http://mock:9000")
    assert config.stubbed_providers() == ["groq", "geoapify"]
    monkeypatch.setenv("GROQ_BASE_URL", "   ")
    assert config.stubbed_providers() == ["geoapify"]
```

(b) In `backend/tests/test_demo_router.py`, add directly after the function
`test_config_with_flag_off_enables_every_mode`:

```python
def test_config_says_how_many_routes_to_request_up_front(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ROUTES_UP_FRONT", raising=False)
    assert _client().get("/config").json()["routes_up_front"] == 1
    monkeypatch.setenv("ROUTES_UP_FRONT", "3")
    assert _client().get("/config").json()["routes_up_front"] == 3
```

(c) In `backend/tests/test_health.py`, add at the end of the file:

```python


def test_health_says_when_a_provider_is_stubbed(monkeypatch):
    monkeypatch.delenv("DEMO_MODE", raising=False)
    monkeypatch.delenv("GROQ_BASE_URL", raising=False)
    monkeypatch.delenv("GEOAPIFY_BASE_URL", raising=False)
    assert "stubbed" not in client.get("/health").json()
    monkeypatch.setenv("GEOAPIFY_BASE_URL", "http://mock:9000")
    assert client.get("/health").json()["stubbed"] is True
```

- [ ] **Step 2: Run them and see them fail**

Run (from `backend/`):
`doppler run -- pytest tests/test_config.py tests/test_demo_router.py tests/test_health.py -q`
Expected: the four new tests fail (`AttributeError: module 'config' has no attribute 'routes_up_front'`,
`KeyError: 'routes_up_front'`, `KeyError: 'stubbed'`).

- [ ] **Step 3: Add the settings**

In `backend/config.py`, at the end of the file, add:

```python


def routes_up_front() -> int:
    """How many candidate facilities the web app routes before the guest asks. 1: only the
    recommended one, the others on demand. 3 brings back routing every candidate at once."""
    return env_int("ROUTES_UP_FRONT", 1, minimum=1, maximum=3)


STUB_SETTINGS: dict[str, str] = {"groq": "GROQ_BASE_URL", "geoapify": "GEOAPIFY_BASE_URL"}


def stubbed_providers() -> list[str]:
    """Providers whose address is overridden. Set on the staging service only, for load tests
    against a mock; an API that answers guests must return an empty list."""
    return [name for name, setting in STUB_SETTINGS.items() if os.environ.get(setting, "").strip()]
```

- [ ] **Step 4: Expose them**

(a) `backend/models.py`, in `class AppConfig`, below the `modes_enabled:` line, add:

```python
    routes_up_front:   int = 1
```

(b) `backend/routers/demo.py`: replace

```python
from config import DOWNTOWN_TORONTO, demo_mode, modes_enabled, starter_prompts
```

with:

```python
from config import DOWNTOWN_TORONTO, demo_mode, modes_enabled, routes_up_front, starter_prompts
```

and in `get_config`, below the line `        modes_enabled=modes_enabled(),`, add:

```python
        routes_up_front=routes_up_front(),
```

(c) `backend/main.py`: replace `from config import demo_mode` with
`from config import demo_mode, stubbed_providers`.

In `lifespan`, directly above the line `    background_tasks = [`, add:

```python
    if stubbed_providers():
        logger.warning("providers_stubbed", extra={"providers": stubbed_providers()})
```

In `health`, directly below the line `    result["demoMode"] = demo_mode()`, add:

```python
    if stubbed_providers():
        result["stubbed"] = True
```

(d) `shared/types.ts`, in `export interface AppConfig`, below the `modes_enabled:` line, add:

```ts
  routes_up_front?:  number   // candidates routed before the guest asks; 1 when absent
```

(e) `webapp/src/lib/config.ts`, in `DEFAULT_CONFIG`, below the `modes_enabled:` line, add:

```ts
  routes_up_front: 1,
```

- [ ] **Step 5: Update `docs/API.md`**

(a) In the section `### GET `/health``, replace

```json
{ "status": "ok", "llmProvider": "groq" }
```

with:

```json
{ "status": "ok", "llmProvider": "groq", "demoMode": true }
```

and add directly below that code block:

```markdown
`"stubbed": true` is added when `GROQ_BASE_URL` or `GEOAPIFY_BASE_URL` is set. That is only
ever the case on the staging service during a load test.
```

(b) In the section `### POST `/routes``, replace the paragraph that starts with
`` `facility_ids`: 1 to 3, unique `` (two lines, ending with `` `transit`, `walk`). ``) with:

```markdown
`facility_ids`: 1 to 3, unique, resolved against the server's facility list. `mode`: `car`,
`bike`, `bus` or `walk` (Geoapify `drive`, `bicycle`, `transit`, `walk`). `severity` (optional):
the triage severity. The web app sends the recommended facility only (`routes_up_front` in
`/config`), and another candidate when the guest selects it.

**Geoapify budget.** The server makes at most `GEOAPIFY_RATE_PER_SECOND` Geoapify calls per
second per process. Past that, a request whose `severity` is `urgent` or `emergent` is still
routed; any other request is answered with `"estimated": true` on each route: `eta_minutes` and
`distance_km` come from the straight-line distance and `geometry` is null.
```

In the same section, in the response example, replace the two route lines with:

```json
    { "facility_id": "<id>", "eta_minutes": 34, "distance_km": 9.8, "geometry": [[43.65, -79.38], [43.66, -79.39]], "estimated": false },
    { "facility_id": "<id>", "eta_minutes": null, "distance_km": null, "geometry": null, "estimated": false }
```

(c) Directly above the line `### GET `/facilities/nearby``, add this section (keep the `---`
separator style of the file):

```markdown
### GET `/facilities`

The facility list with current wait times. Optional query parameters: `category`, `severity`,
`max_wait_minutes`.

The body is encoded once per data version (facility list and wait-time data) and filter set.
Response headers:

| Header | Meaning |
|---|---|
| `ETag` | Changes when the facility list, the wait-time data or a filter changes |
| `Cache-Control: max-age=N` | N seconds until the wait-time worker's next run, at least `MAP_MIN_MAX_AGE_SECONDS` |
| `X-Wait-As-Of` | Time of the worker's last successful run (ISO 8601). Absent when unknown |

A request with a matching `If-None-Match` gets `304` with the same headers and no body.

### POST `/chat/message` when the server is busy

Past `MAX_TURNS_IN_FLIGHT` turns in flight in a process, a turn is refused at once with
`429 {"code": "busy", "retry_after": N}` (N is 3 to 5 seconds by default). Nothing is stored
and the guest's rate-limit allowance is not used, so the client sends the same message again.
A failed read of the conversation history answers `503`.

---

```

(d) In the section `### Settings`, add these rows at the end of the table (directly below the
row for `OPENAI_API_KEY`, `OPENAI_MODEL`):

```markdown
| `WAIT_CACHE_TTL_SECONDS` | 30 (1 to 900) | How often the API reloads wait-time data into memory (plus up to 20%) |
| `MAP_MIN_MAX_AGE_SECONDS` | 30 (1 to 900) | Smallest `max-age` sent with `/facilities` |
| `LLM_MAX_CONNECTIONS` | 2000 (1 to 20000) | Connections each provider client may hold; caps LLM calls in flight |
| `CHAT_HISTORY_MESSAGES` | 20 (1 to 200) | Messages of a session read from the store for each turn |
| `MAX_TURNS_IN_FLIGHT` | 0 (no limit) | Chat turns in flight per process before the busy answer |
| `ADMISSION_RETRY_SECONDS` | 3 (1 to 60) | `retry_after` of that busy answer, plus 0 to 2 seconds |
| `LOAD_AWARE_ROUTING` | on | `off` recommends the nearest facility for every severity |
| `LOAD_SCORE_TIE_MINUTES` | 5 (0 to 120) | Candidates within this many minutes of the best score are a tie |
| `LOAD_WINDOW_MINUTES` | 15 (1 to 120) | How far back recent recommendations count as load |
| `ROUTES_UP_FRONT` | 1 (1 to 3) | Candidates the web app routes before the guest asks |
| `GEOAPIFY_RATE_PER_SECOND` | 5 (1 to 1000) | Geoapify calls per second per process; the plan's rate divided by the number of processes |
| `GROQ_BASE_URL`, `GEOAPIFY_BASE_URL` | unset | Point the API at a mock. Staging service only, never in Doppler `stg` |
```

(e) In the metrics table of the section `### GET `/metrics``, add these rows directly below the
row for `demo_db_pool_size`, `demo_db_pool_in_use`, `demo_db_pool_waiting`:

```markdown
| `chat_turns_in_flight` | gauge | none |
| `chat_turns_rejected_total` | counter | none |
| `routes_degraded_total` | counter | none |
```

- [ ] **Step 6: Run the tests and commit**

Run (from `backend/`): `doppler run -- pytest -q` — expected: no failure.
Run (from `webapp/`): `npx tsc -b` and `doppler run -- npm run test` — expected: no error, all pass.

```bash
git add backend/config.py backend/models.py backend/routers/demo.py backend/main.py shared/types.ts webapp/src/lib/config.ts docs/API.md backend/tests/test_config.py backend/tests/test_demo_router.py backend/tests/test_health.py
git commit -m "feat(api): expose the routes-up-front setting and flag stubbed providers"
```

---

### Task 16: The web app routes one facility up front and the others on demand

**Files:**
- Modify: `webapp/src/lib/routesClient.ts`, `webapp/src/lib/triageRoutes.ts`,
  `webapp/src/hooks/useTriageState.ts` (replaced),
  `webapp/src/components/triage/TriageCard.tsx`,
  `webapp/src/components/mobile/FacilityCardPanel.tsx`
- Test: `webapp/src/lib/routesClient.test.ts`, `webapp/src/lib/triageRoutes.test.ts`

**Interfaces:**
- Consumes: `AppConfig.routes_up_front` (task 15), `RoutesRequest.severity` and
  `CandidateRoute.estimated` (task 14).
- Produces:
  - `fetchRoutes(origin, facilityIds, mode, severity?)`.
  - `candidateIds(state, upFront?)`, `mergeRoutes(state, response)`; `toRouteResults` carries
    `estimated: true` through.
  - `useTriageState().selectFacility(facilityId)` fetches the route of a candidate that has
    none yet.

- [ ] **Step 1: Write the failing tests**

(a) In `webapp/src/lib/routesClient.test.ts`, inside `describe("fetchRoutes", ...)`, add after
the first `it(...)` block:

```ts
  it("sends the severity when it is given", async () => {
    apiFetch.mockResolvedValue({ ok: true, json: async () => RESPONSE })
    await fetchRoutes(ORIGIN, ["a"], "car", "emergent")
    const [, options] = apiFetch.mock.calls[0] as [string, RequestInit]
    expect(JSON.parse(String(options.body))).toEqual({
      origin: ORIGIN, facility_ids: ["a"], mode: "car", severity: "emergent",
    })
  })

  it("leaves the severity out when there is none", async () => {
    apiFetch.mockResolvedValue({ ok: true, json: async () => RESPONSE })
    await fetchRoutes(ORIGIN, ["a"], "car", null)
    const [, options] = apiFetch.mock.calls[0] as [string, RequestInit]
    expect(JSON.parse(String(options.body))).toEqual({ origin: ORIGIN, facility_ids: ["a"], mode: "car" })
  })
```

(b) In `webapp/src/lib/triageRoutes.test.ts`:

Replace the import line

```ts
import { applyRoutes, candidateIds, promoteFacility, toRouteResults } from "./triageRoutes"
```

with:

```ts
import { applyRoutes, candidateIds, mergeRoutes, promoteFacility, toRouteResults } from "./triageRoutes"
```

Inside `describe("candidateIds", ...)`, add:

```ts
  it("keeps only the first ones when a number up front is given", () => {
    expect(candidateIds(BASE, 1)).toEqual(["a"])
    expect(candidateIds(BASE, 2)).toEqual(["a", "b"])
    expect(candidateIds(BASE, 3)).toEqual(["a", "b", "c"])
  })
```

Inside `describe("toRouteResults", ...)`, add:

```ts
  it("carries the estimated flag of a route that was not drawn", () => {
    const estimated: RoutesResponse = {
      mode: "car",
      routes: [{ facility_id: "a", eta_minutes: 7, distance_km: 2.1, geometry: null, estimated: true }],
      fastest_facility_id: "a",
    }
    expect(toRouteResults(estimated)).toEqual([
      { facilityId: "a", etaMinutes: 7, distanceKm: 2.1, geometry: null, estimated: true },
    ])
  })
```

At the end of the file add:

```ts

describe("mergeRoutes", () => {
  const onlyA: RoutesResponse = {
    mode: "bike",
    routes: [{ facility_id: "a", eta_minutes: 20, distance_km: 5.1, geometry: LINE_A }],
    fastest_facility_id: "a",
  }
  const onlyB: RoutesResponse = {
    mode: "bike",
    routes: [{ facility_id: "b", eta_minutes: 9, distance_km: 2.4, geometry: LINE_B }],
    fastest_facility_id: "b",
  }
  const shown = applyRoutes(BASE, "bike", onlyA)

  it("adds the new route and keeps the ones already there", () => {
    const next = mergeRoutes({ ...shown, routeLoading: true }, onlyB)
    expect(next.routes.map(r => r.facilityId)).toEqual(["a", "b"])
    expect(next.routeLoading).toBe(false)
  })

  it("does not move the recommendation", () => {
    const next = mergeRoutes(shown, onlyB)
    expect(next.recommendedFacilityId).toBe("a")
    expect(next.roadGeometry).toEqual(LINE_A)
  })

  it("replaces a route for the same facility", () => {
    const faster: RoutesResponse = {
      ...onlyA, routes: [{ facility_id: "a", eta_minutes: 12, distance_km: 5.1, geometry: LINE_A }],
    }
    expect(mergeRoutes(shown, faster).routes).toEqual([
      { facilityId: "a", etaMinutes: 12, distanceKm: 5.1, geometry: LINE_A },
    ])
  })

  it("lets the merged route be promoted", () => {
    const next = promoteFacility(mergeRoutes(shown, onlyB), "b")
    expect(next.recommendedFacilityId).toBe("b")
    expect(next.roadGeometry).toEqual(LINE_B)
    expect(next.nearbyFacilities).toEqual([A, C])
  })
})
```

- [ ] **Step 2: Run them and see them fail**

Run (from `webapp/`): `doppler run -- npm run test -- src/lib/triageRoutes.test.ts src/lib/routesClient.test.ts`
Expected: FAIL, `mergeRoutes is not a function` and the severity assertion fails.

- [ ] **Step 3: Change `webapp/src/lib/routesClient.ts`**

Replace the whole file with:

```ts
import type { RoutesRequest, RoutesResponse, Severity, TravelModeKey } from "@shared/types"
import { apiFetch } from "./apiClient"

/**
 * Routes from `origin` to the candidate facilities for one travel mode. Returns null on any
 * failure (rate limit, no route, network): the map then keeps its straight-line fallback.
 * `severity` lets the server keep routing urgent and emergent cases when its Geoapify budget
 * is spent.
 */
export async function fetchRoutes(
  origin: { lat: number; lng: number },
  facilityIds: string[],
  mode: TravelModeKey,
  severity?: Severity | null,
): Promise<RoutesResponse | null> {
  if (facilityIds.length === 0) return null
  const body: RoutesRequest = { origin, facility_ids: facilityIds, mode, ...(severity ? { severity } : {}) }
  try {
    const res = await apiFetch("/routes", { method: "POST", body: JSON.stringify(body) })
    if (!res.ok) return null
    return (await res.json()) as RoutesResponse
  } catch {
    return null
  }
}
```

- [ ] **Step 4: Change `webapp/src/lib/triageRoutes.ts`**

(a) Replace the `candidateIds` function and its comment with:

```ts
/**
 * Ids sent to POST /routes: the recommended facility first, then the alternatives. `upFront`
 * keeps only the first ones (1: the recommended facility alone).
 */
export function candidateIds(state: TriageUIState, upFront: number = Number.POSITIVE_INFINITY): string[] {
  return candidates(state).slice(0, upFront).map(f => f.id)
}
```

(b) Replace the `toRouteResults` function and its comment with:

```ts
/** Candidates the backend could not route are dropped: a time is real, estimated, or absent. */
export function toRouteResults(response: RoutesResponse): RouteResult[] {
  return response.routes.flatMap(route =>
    route.eta_minutes === null || route.distance_km === null
      ? []
      : [{
          facilityId: route.facility_id,
          etaMinutes: route.eta_minutes,
          distanceKm: route.distance_km,
          geometry:   route.geometry,
          ...(route.estimated ? { estimated: true } : {}),
        }],
  )
}
```

(c) At the end of the file add:

```ts

/**
 * Adds the routes of a POST /routes answer for the mode already on screen, keeping the ones
 * already there. The recommendation does not move: the caller promotes a facility if it wants to.
 */
export function mergeRoutes(state: TriageUIState, response: RoutesResponse): TriageUIState {
  const incoming = toRouteResults(response)
  const replaced = new Set(incoming.map(route => route.facilityId))
  return {
    ...state,
    routes: [...state.routes.filter(route => !replaced.has(route.facilityId)), ...incoming],
    routeLoading: false,
  }
}
```

Run (from `webapp/`): `doppler run -- npm run test -- src/lib/triageRoutes.test.ts src/lib/routesClient.test.ts`
Expected: all pass.

- [ ] **Step 5: Replace `webapp/src/hooks/useTriageState.ts`**

```ts
import { useCallback, useRef, useState } from "react"
import type { RoutesResponse, TravelModeKey, TriageResult, TriageUIState } from "../../../shared/types"
import { getConfig } from "../lib/config"
import { postModeChanged, postRouteDrawn } from "../lib/guestEvents"
import { fetchRoutes } from "../lib/routesClient"
import { applyRoutes, candidateIds, mergeRoutes, promoteFacility } from "../lib/triageRoutes"

const DEFAULT_MODE: TravelModeKey = "car"
const DEFAULT_ROUTES_UP_FRONT = 1

const DEFAULT_STATE: TriageUIState = {
  active: false,
  severity: null,
  reasoning: null,
  recommendedFacility: null,
  nearbyFacilities: [],
  userCoords: null,
  routes: [],
  recommendedFacilityId: null,
  roadGeometry: null,
  travelMode: DEFAULT_MODE,
  routeLoading: false,
}

/** How many candidates are routed before the guest asks: 1 unless the server says otherwise. */
async function routesUpFront(): Promise<number> {
  return (await getConfig()).routes_up_front ?? DEFAULT_ROUTES_UP_FRONT
}

function cacheKey(mode: TravelModeKey, facilityIds: string[]): string {
  return `${mode}:${facilityIds.join(",")}`
}

export function useTriageState() {
  const [triage, setTriage] = useState<TriageUIState>(DEFAULT_STATE)
  // The async actions below need the latest state, not the one captured when they started.
  const stateRef = useRef<TriageUIState>(DEFAULT_STATE)
  // One POST /routes answer per travel mode and set of facilities, for the current triage only.
  const cacheRef = useRef(new Map<string, RoutesResponse>())
  // Bumped on every new request: an answer whose number is no longer current is dropped.
  const requestRef = useRef(0)
  const sessionRef = useRef<string | null>(null)

  const commit = useCallback((next: TriageUIState) => {
    stateRef.current = next
    setTriage(next)
  }, [])

  const reset = useCallback(() => {
    requestRef.current += 1
    cacheRef.current = new Map()
    sessionRef.current = null
    commit(DEFAULT_STATE)
  }, [commit])

  const applyTriageResult = useCallback(async (
    result: TriageResult,
    userCoords: { lat: number; lng: number } | null,
    sessionId?: string | null,
  ) => {
    const requestId = ++requestRef.current
    cacheRef.current = new Map()
    sessionRef.current = sessionId ?? null

    if (!result.recommended_facility) {
      commit({
        ...DEFAULT_STATE,
        active: true,
        severity: result.severity,
        reasoning: result.reasoning,
        nearbyFacilities: result.nearby_facilities,
        userCoords,
      })
      return
    }

    const base: TriageUIState = {
      ...DEFAULT_STATE,
      active: true,
      severity: result.severity,
      reasoning: result.reasoning,
      recommendedFacility: result.recommended_facility,
      nearbyFacilities: result.nearby_facilities,
      userCoords,
      recommendedFacilityId: result.recommended_facility.id,
      routeLoading: userCoords !== null,
    }
    commit(base)
    if (!userCoords) return

    // Only the recommended facility is routed now; the others when the guest selects them.
    const ids = candidateIds(base, await routesUpFront())
    if (requestId !== requestRef.current) return
    const response = await fetchRoutes(userCoords, ids, DEFAULT_MODE, base.severity)
    if (requestId !== requestRef.current) return
    if (!response) {
      commit({ ...stateRef.current, routeLoading: false })
      return
    }
    cacheRef.current.set(cacheKey(DEFAULT_MODE, ids), response)
    const next = applyRoutes(stateRef.current, DEFAULT_MODE, response)
    commit(next)
    // Only real road geometry counts as "route drawn"; the straight-line fallback does not.
    if (next.roadGeometry && sessionId) void postRouteDrawn(sessionId, DEFAULT_MODE)
  }, [commit])

  const changeMode = useCallback(async (mode: TravelModeKey) => {
    const current = stateRef.current
    if (!current.active || !current.userCoords || !current.recommendedFacility) return
    if (current.routeLoading) return
    // Same mode with routes already shown: nothing to do. Same mode without routes: a retry.
    if (mode === current.travelMode && current.routes.length > 0) return

    const coords = current.userCoords
    const shownFacilityId = current.recommendedFacility.id
    const requestId = ++requestRef.current
    const startedAt = performance.now()
    commit({ ...current, routeLoading: true })

    const upFront = await routesUpFront()
    if (requestId !== requestRef.current) return
    // With one route up front, a mode change routes the facility on screen, not every candidate.
    const ids = upFront > 1 ? candidateIds(current, upFront) : [shownFacilityId]
    const key = cacheKey(mode, ids)

    const cached = cacheRef.current.get(key)
    if (cached) {
      commit(applyRoutes(stateRef.current, mode, cached))
      return
    }

    const response = await fetchRoutes(coords, ids, mode, current.severity)
    if (requestId !== requestRef.current) return
    if (!response) {
      // Keep the previous mode and its route on screen.
      commit({ ...stateRef.current, routeLoading: false })
      return
    }
    cacheRef.current.set(key, response)
    const next = applyRoutes(stateRef.current, mode, response)
    commit(next)

    const sessionId = sessionRef.current
    if (!sessionId || !next.roadGeometry) return
    // Measured on the next animation frame, after React has rendered and the map layer has redrawn.
    requestAnimationFrame(() => {
      void postModeChanged(sessionId, mode, performance.now() - startedAt)
      void postRouteDrawn(sessionId, mode)
    })
  }, [commit])

  const selectFacility = useCallback(async (facilityId: string) => {
    const current = stateRef.current
    if (!current.active || current.routeLoading) return
    if (current.routes.some(route => route.facilityId === facilityId)) {
      commit(promoteFacility(current, facilityId))
      return
    }
    // No route for this candidate yet: it was not routed up front. Ask for it now.
    const coords = current.userCoords
    if (!coords) return
    const requestId = ++requestRef.current
    commit({ ...current, routeLoading: true })

    const response = await fetchRoutes(coords, [facilityId], current.travelMode, current.severity)
    if (requestId !== requestRef.current) return
    if (!response) {
      commit({ ...stateRef.current, routeLoading: false })
      return
    }
    commit(promoteFacility(mergeRoutes(stateRef.current, response), facilityId))
  }, [commit])

  return { triage, applyTriageResult, changeMode, selectFacility, reset }
}
```

- [ ] **Step 6: Let the other candidates be selected, and say when a route is estimated**

(a) In `webapp/src/components/triage/TriageCard.tsx`, in the `otherFacilities.map(...)` button:

Replace `                disabled={!route?.geometry}` with:

```tsx
                disabled={triage.routeLoading}
```

Replace `                  cursor: route?.geometry ? "pointer" : "default",` with:

```tsx
                  cursor: triage.routeLoading ? "progress" : "pointer",
```

Replace

```tsx
                    {route ? `${route.etaMinutes} min` : `~${facility.distanceKm} km`}
```

with:

```tsx
                    {route ? `${route.estimated ? "~" : ""}${route.etaMinutes} min` : `~${facility.distanceKm} km`}
```

(b) In the same file, directly above the line
`            {/* Directions CTA — all non-emergent severities */}`, add:

```tsx
            {recommendedRoute?.estimated && (
              <div
                role="status"
                data-testid="route-estimated"
                style={{ fontSize: 10, color: "#7AA0B0", marginBottom: 8 }}
              >
                Route unavailable right now. The time shown is an estimate. If this is an emergency, call 911.
              </div>
            )}

```

(c) In `webapp/src/components/mobile/FacilityCardPanel.tsx`, replace

```tsx
        <TransitModeGrid
          etaMinutes={recommendedRoute?.etaMinutes ?? null}
          activeMode={triage.travelMode}
          loading={triage.routeLoading}
          onModeChange={onModeChange}
        />
```

with:

```tsx
        <TransitModeGrid
          etaMinutes={recommendedRoute?.etaMinutes ?? null}
          activeMode={triage.travelMode}
          loading={triage.routeLoading}
          onModeChange={onModeChange}
        />
        {recommendedRoute?.estimated && (
          <p
            role="status"
            data-testid="route-estimated"
            className="px-4 pt-2 text-[10px]"
            style={{ color: '#85A4B1' }}
          >
            Route unavailable right now. The time shown is an estimate. If this is an emergency, call 911.
          </p>
        )}
```

- [ ] **Step 7: Check types and tests**

Run (from `webapp/`): `npx tsc -b` — expected: no error. If the compiler reports that a
component passes `selectFacility` where a function returning `void` is expected, that is
accepted by TypeScript and needs no change; any other error: stop and report.
Run (from `webapp/`): `doppler run -- npm run test` — expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add webapp/src/lib/routesClient.ts webapp/src/lib/routesClient.test.ts webapp/src/lib/triageRoutes.ts webapp/src/lib/triageRoutes.test.ts webapp/src/hooks/useTriageState.ts webapp/src/components/triage/TriageCard.tsx webapp/src/components/mobile/FacilityCardPanel.tsx
git commit -m "feat(web): route the recommended facility first and the others when selected"
```

---

## CHECKPOINT 3

Stop here. Report: the seven commit hashes, the output of the whole backend suite, the worker
suite and the web suite, the table printed by `bench_lookup`, and anything that did not apply
as written. Wait for review. Do not push and do not open a pull request.

---

# Part 4: runbooks run by the engineer (not part of the three batches)

These phases need the Railway dashboard, the admin tunnel, Doppler and judgement on live
numbers. They are run directly, with the owner, from the spec. They are listed here so the
order of the whole sprint is in one place.

### Phase 0, before task 1 is deployed anywhere (spec section 4)

- [ ] Bring `medicoordai-staging` back: 1 worker, 1 vCPU, 1 GB, pointed at `feat/demo-scaling`.
- [ ] Load-test guest rows in the demo database: dry run with counts, then apply, through the
      tunnel. Report the non-internal row starting `8fe1df4f`; do not delete it.
- [ ] Memory profile of a short Test B run with `tracemalloc` (staging-only `MEMORY_PROFILE`
      switch, added as a small change of its own). Record the top allocation sites by growth.
      Read the result before part 2 is deployed: it decides whether anything beyond task 6
      (clients built once) is needed.

### After each checkpoint

- [ ] Compare the committed files with this plan's code blocks.
- [ ] Deploy the branch to staging and run the four-scenario smoke suite.
- [ ] After checkpoint 2: run the 27-vignette triage check on the default provider and compare
      with the run taken before part 2. The result must be the same.
- [ ] Deploy the worker together with part 1 (task 1 changes it).

### Phase 4: harness (spec section 8)

- [ ] Mock provider under `backend/scripts/load/`: Groq chat-completions and Geoapify routing,
      canned replies, delays from the Sprint 21 distributions. Second staging service, reached
      through `GROQ_BASE_URL` and `GEOAPIFY_BASE_URL` set on the staging service only. Check
      `/health` reports `"stubbed": true` there and not on python-api.
- [ ] Test B: steps to 2,000, conversations of two or three turns, origins spread over the
      city, busy answers counted apart from failures. Test A: `If-None-Match` on a share of
      requests.
- [ ] Docker Compose: load balancer, N API replicas with fixed CPU and memory, Postgres, Redis,
      mock. The four checks of spec section 8.3 at 1, 2 and 4 replicas.

### Phase 5: measurement (spec section 9)

- [ ] Runs 1 to 7 in order, run 8 only if the breakpoint is below 1,000. All on staging.
- [ ] Set `MAX_TURNS_IN_FLIGHT`, `DEMO_DB_POOL_MAX` and `GEOAPIFY_RATE_PER_SECOND` from the
      results.
- [ ] One report under `artifacts/perf/`, summary in `CHANGELOG.md`.

### Phase 6: close-out (spec section 10)

- [ ] New `METRICS_BEARER_TOKEN`, Grafana Cloud scrape job.
- [ ] Move python-api and the demo Postgres to US East; smoke suite and a short verification run.
- [ ] Real-call OpenAI test, `ANTHROPIC_MODEL` in Doppler `stg`, `VITE_GEOAPIFY_API_KEY` removed.
- [ ] Pull request to `preview`.

---

## Design lenses used

- **release-it:** fail fast at the admission limit instead of an unbounded queue (task 8); a
  bulkhead around the routing vendor with a degraded answer (task 14); explicit connection
  limits instead of SDK defaults (task 5); every new behaviour behind a setting that restores
  the previous one (`MAX_TURNS_IN_FLIGHT=0`, `LOAD_AWARE_ROUTING=off`, `ROUTES_UP_FRONT=3`).
- **ddia-systems:** Postgres as the only copy of a conversation (task 7); the encoded facility
  list, the cell index and the load totals as derived data rebuilt from a version or a window
  (tasks 3, 10, 12); atomic increments instead of locks (task 12); staleness of wait data made
  explicit by the worker's stamp (tasks 1 and 2).
- **system-design:** two-stage lookup, a coarse cell filter then exact ranking (task 10);
  stateless processes so replicas add capacity (tasks 7, 8, 12).
- **clean-architecture:** the agent depends on `BaseLLMClient` only, so going async changed the
  interface and its implementations and left the triage rules alone (tasks 5 and 6); each new
  concern is one module with one job, and `metrics.py` still imports none of them.
- **pragmatic-programmer:** deletion of `cache_chat.py` rather than repair (task 7); one
  definition of the worker interval and of the travel speeds (tasks 2 and 11); the scan kept
  as the always-correct fallback of the index (task 10).
- **clean-code:** existing function signatures and response shapes kept wherever behaviour is
  unchanged; an unreadable history is an explicit error, not an empty list (task 7).
- **test-driven-development:** every task adds its tests first and states the failure to
  expect; the index is tested against a copy of the scan it replaces (task 10).
