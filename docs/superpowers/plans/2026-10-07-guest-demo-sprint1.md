# Guest Demo Sprint 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A public, sign-in-free guest demo (chat → facility recommendation → route on the map) behind `DEMO_MODE`, with feedback, three events and a rate limit, backed by the Railway demo Postgres.

**Architecture:** `config.demo_mode()` is the single switch. With it on, a `get_actor` dependency turns the `X-Guest-Id` header into a guest, and the three services (`facilities`, `wait_times`, `chat`) read and write the demo Postgres through `services/guest_store.py` and a psycopg pool in `demo_db.py`; with it off, the Supabase path is untouched. The frontend learns the flag from `GET /config` and `AuthProvider` exposes the guest as `user`.

**Tech Stack:** Python 3.11, FastAPI, psycopg 3 + `psycopg_pool`, Alembic, Redis, pytest · React 19, Vite, TypeScript strict, Vitest, Playwright.

**Spec:** [`docs/superpowers/specs/2026-10-07-guest-demo-sprint1-design.md`](../specs/2026-10-07-guest-demo-sprint1-design.md)

## Global Constraints

- Severity values are exactly `routine | moderate | urgent | emergent`. Flag any other value; do not silently fix it.
- TypeScript: strict, no `any`, every props object has an interface. Python: type hints on every signature, Pydantic models for every request/response body.
- A new backend route needs its type in `shared/types.ts` first (Task 1).
- No new npm packages. The only new Python dependency is `psycopg_pool==3.*` (added to `backend/requirements.txt`).
- Python commands: `source /home/niki/Documents/workenv/pydev/bin/activate` first; env vars through `doppler run --`.
- Never print or log secrets. `backend/.env.demo.local` is read only through `backend/script.demo.local.sh` or python-dotenv, never `cat`.
- Do not touch Supabase schema or data. Do not stop other projects' containers (port 5432 is not ours; the rehearsal DB is `medicoord-demo-pg` on 5433).
- Remote database writes (migration `0004`) and any production-writing action need the user's explicit go-ahead each time.
- Commits: every commit step means "show the staged files and the message, wait for the user's approval, then commit". Conventional one-line message, no co-author trailer, never on `main`/`preview`, one commit per task.
- Before reading or grepping source files, run `graphify query "<question>"` (project hook). After code changes, run `graphify update .`.
- Rate limit: 10 per guest and 30 per IP per 600 s, `POST /chat/message` only. Busy body: `{"code": "busy", "retry_after": <int seconds>}`.
- Retention: sessions (and their messages) are deleted 30 days after `sessions.created_at`. No IP address is stored in Postgres or logs.
- Toronto box: lat 43.58–43.86, lng −79.64 to −79.12. Downtown fallback: lat 43.6532, lng −79.3832.
- Notice text, verbatim: `Not medical advice. In an emergency call 911.`

## Review Focus

Each line names the task whose tests pin it.

1. **A guest sends another guest's `session_id`** → 404, nothing written (Task 4: `test_add_message_rejects_foreign_session`, `test_feedback_rejects_foreign_message`).
2. **`X-Guest-Id` or a path id that is not a UUID** (empty, `abc`, SQL text) → 400 / 404, never a 500 from the driver (Task 5: `test_guest_header_malformed_is_400`; Task 4: `test_older_messages_bad_uuid_is_empty`).
3. **Browser preflight with the new headers** → CORS allows `X-Guest-Id` and `X-Internal`; without it every guest call fails in the browser while curl works (Task 5: `test_cors_allows_guest_headers`).
4. **Redis is down** → chat still works, limiter allows, purge still runs (Task 7: `test_rate_limit_fails_open`; Task 8: `test_purge_runs_when_redis_down`).
5. **`localStorage` is blocked or holds garbage** (private mode, edited value) → the app still gets a valid UUID (Task 9: `returns a fresh id when storage holds garbage`, `falls back to memory when storage throws`).

---

## File Structure

**Backend (create)**
- `backend/config.py` — `demo_mode()` and demo constants.
- `backend/demo_db.py` — the psycopg pool and `fetch_all` / `fetch_one` / `execute`.
- `backend/services/guest_store.py` — all SQL for guests, sessions, messages, feedback, events, purge.
- `backend/services/rate_limit.py` — fixed-window limiter and the busy response.
- `backend/services/retention.py` — hourly-throttled purge trigger.
- `backend/routers/demo.py` — `/config`, `/feedback`, `/events`.
- `migrations/postgres/versions/20261007_0004_guest_tables.py`
- Tests: `backend/tests/test_config.py`, `test_guest_store.py`, `test_actor.py`, `test_rate_limit.py`, `test_demo_router.py`, `test_retention.py`, `test_demo_services.py`.

**Backend (modify)**
- `backend/models.py`, `backend/main.py`, `backend/middleware/auth.py`, `backend/routers/chat.py`, `backend/services/{facilities,wait_times,chat}.py`, `backend/requirements.txt`, `backend/tests/{test_chat,test_facilities_routes}.py`.

**Shared:** `shared/types.ts`.

**Frontend (create)**
- `webapp/src/lib/config.ts`, `lib/guest.ts`, `lib/demoLocation.ts`, `lib/busy.ts`, `lib/guestEvents.ts`, `hooks/useConfig.ts`, `components/triage/FeedbackControl.tsx`, `components/MedicalNotice.tsx`.
- Tests: `lib/guest.test.ts`, `lib/config.test.ts`, `lib/demoLocation.test.ts`, `lib/busy.test.ts`; additions to `utils/waitTimeUtils.test.ts`.
- `webapp/playwright.smoke.config.ts`, `webapp/e2e/guest-demo.smoke.spec.ts`.

**Frontend (modify)**
- `auth/AuthContext.tsx`, `lib/apiClient.ts`, `hooks/{useProfile,useConversations,useTriageState}.ts`, `App.tsx`, `Menucomponents/Home.tsx`, `Menucomponents/subcomponent/ChatPanel.tsx`, `components/mobile/{MobileLayout,BottomSheet,SuggestionChips,TransitModeGrid,FacilityCardPanel,DrawerMenu}.tsx`, `components/map/MapPanel.tsx`, `components/map/components/{UnifiedFacilityPopup,FacilityMarkerLayer}.tsx`, `components/triage/TriageCard.tsx`, `components/GpsPermissionModal.tsx`, `components/legal/LegalPageLayout.tsx`, `pages/{LandingPage,DataDisclosurePage}.tsx`, `utils/waitTimeUtils.ts`.

**Delete:** `webapp/src/Menucomponents/utils/geoapify.ts`.

**Docs:** `CLAUDE.md`, `CHANGELOG.md`, `docs/API.md`.

---

# Milestone 1 — Backend

### Task 1: Contracts (`shared/types.ts`, `models.py`)

**Files:**
- Modify: `shared/types.ts`
- Modify: `backend/models.py`
- Test: `backend/tests/test_models.py` (append)

**Interfaces:**
- Produces (TS): `TravelModeKey`, `AppConfig`, `Thumb`, `FeedbackRequest`, `GuestEventRequest`, `BusyResponse`; `Facility.raw_wait?`, `Facility.predicted?`.
- Produces (Python): `AppConfig`, `LatLng`, `FeedbackRequest`, `GuestEventRequest` Pydantic models; `Facility.raw_wait`, `Facility.predicted`.

- [ ] **Step 1: Write the failing test** — append to `backend/tests/test_models.py`:

```python
import pytest
from pydantic import ValidationError

from models import AppConfig, FeedbackRequest, GuestEventRequest, Facility

_SID = "00000000-0000-0000-0000-0000000000a1"
_MID = "00000000-0000-0000-0000-0000000000a2"


def test_feedback_request_accepts_up_and_down_only() -> None:
    assert FeedbackRequest(session_id=_SID, message_id=_MID, thumb="up").comment is None
    with pytest.raises(ValidationError):
        FeedbackRequest(session_id=_SID, message_id=_MID, thumb="meh")


def test_feedback_comment_is_capped_at_2000_chars() -> None:
    with pytest.raises(ValidationError):
        FeedbackRequest(session_id=_SID, message_id=_MID, thumb="down", comment="x" * 2001)


def test_guest_event_only_accepts_route_drawn_from_clients() -> None:
    assert GuestEventRequest(type="route_drawn", session_id=_SID).type == "route_drawn"
    with pytest.raises(ValidationError):
        GuestEventRequest(type="session_started", session_id=_SID)


def test_app_config_shape() -> None:
    cfg = AppConfig(demo_mode=True, starter_prompts=["a"],
                    downtown_fallback={"lat": 43.6532, "lng": -79.3832}, modes_enabled=["car"])
    assert cfg.model_dump()["downtown_fallback"] == {"lat": 43.6532, "lng": -79.3832}


def test_facility_carries_wait_details() -> None:
    fields = Facility.model_fields
    assert "raw_wait" in fields and "predicted" in fields
```

- [ ] **Step 2: Run it to see it fail**

Run: `cd backend && doppler run -- python -m pytest tests/test_models.py -q`
Expected: FAIL with `ImportError: cannot import name 'AppConfig'`.

- [ ] **Step 3: Add the TypeScript contracts** — in `shared/types.ts`, add two fields at the end of `interface Facility`:

```ts
  raw_wait?:            string | null;
  predicted?:           boolean;
```

and append at the end of the file:

```ts
// ── Guest demo ────────────────────────────────────────────────────────────────

export type TravelModeKey = "car" | "bike" | "bus" | "walk"

export interface AppConfig {
  demo_mode:         boolean
  starter_prompts:   string[]
  downtown_fallback: { lat: number; lng: number }
  modes_enabled:     TravelModeKey[]
}

export type Thumb = "up" | "down"

export interface FeedbackRequest {
  session_id: string
  message_id: string
  thumb:      Thumb
  comment?:   string | null
}

export interface GuestEventRequest {
  type:       "route_drawn"
  session_id: string
}

export interface BusyResponse {
  code:        "busy"
  retry_after: number
}
```

- [ ] **Step 4: Add the Pydantic models** — in `backend/models.py`, change the first import line to `from typing import Literal` plus the existing imports, add to `class Facility` after `wait_minutes`:

```python
    raw_wait:             str | None = None
    predicted:            bool = False
```

and append at the end of the file:

```python
class LatLng(BaseModel):
    lat: float
    lng: float


class AppConfig(BaseModel):
    demo_mode:         bool
    starter_prompts:   list[str]
    downtown_fallback: LatLng
    modes_enabled:     list[Literal["car", "bike", "bus", "walk"]]


class FeedbackRequest(BaseModel):
    session_id: UUID
    message_id: UUID
    thumb:      Literal["up", "down"]
    comment:    str | None = Field(default=None, max_length=2000)


class GuestEventRequest(BaseModel):
    type:       Literal["route_drawn"]
    session_id: UUID
```

- [ ] **Step 5: Run the tests**

Run: `cd backend && doppler run -- python -m pytest tests/test_models.py -q` → PASS.
Run: `cd webapp && npx tsc -b` → no errors.

- [ ] **Step 6: Commit** (after approval)

```bash
git add shared/types.ts backend/models.py backend/tests/test_models.py
git commit -m "feat: add guest demo api contracts"
```

---

### Task 2: Migration 0004 — guest tables, grants, RLS

**Files:**
- Create: `migrations/postgres/versions/20261007_0004_guest_tables.py`
- Modify (git-ignored, local only): `backend/script.demo.local.sh` `cmd_verify`

**Interfaces:**
- Consumes: env `DEMO_APP_ROLE` (same as revision 0002).
- Produces: tables `guests`, `sessions`, `messages`, `feedback`, `events`; unique index `events_session_type_key (session_id, type) where session_id is not null`; unique `feedback.message_id`.

- [ ] **Step 1: Write the migration**

```python
"""guest tables: guests, sessions, messages, feedback, events

Guest-keyed chat for the public demo. `feedback.session_id/message_id` and `events.session_id`
carry no foreign key on purpose: the 30-day purge deletes sessions (messages cascade) and those
rows must survive it.

The backend role gains just what the demo needs. It can delete only from `sessions` (the purge);
messages go by cascade, which runs with the table owner's rights. Isolation between guests is
done in SQL (`where guest_id = ...`): the backend connects as one role, so RLS policies here are
per role, not per guest.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-07
"""
import os
import re

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

_NAME = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")

# table -> commands the backend role may run
GRANTS = {
    "guests":   ("select", "insert", "update"),
    "sessions": ("select", "insert", "update", "delete"),
    "messages": ("select", "insert"),
    "feedback": ("select", "insert", "update"),
    "events":   ("select", "insert"),
}


def _role(var: str) -> str:
    name = os.environ.get(var, "").strip()
    if not _NAME.match(name):
        raise RuntimeError(f"{var} must be set to a lower-case role name (got {name!r})")
    return name


def upgrade() -> None:
    app = _role("DEMO_APP_ROLE")

    op.execute(
        """
        create table guests (
            id           uuid primary key,
            created_at   timestamptz not null default now(),
            last_seen_at timestamptz not null default now(),
            is_internal  boolean not null default false
        )
        """
    )
    op.execute(
        """
        create table sessions (
            id         uuid primary key default gen_random_uuid(),
            guest_id   uuid not null references guests (id) on delete cascade,
            title      text not null,
            created_at timestamptz not null default now(),
            updated_at timestamptz not null default now()
        )
        """
    )
    op.execute("create index sessions_guest_updated_idx on sessions (guest_id, updated_at desc)")
    op.execute("create index sessions_created_idx on sessions (created_at)")
    op.execute(
        "create trigger sessions_set_updated_at before update on sessions "
        "for each row execute function set_updated_at()"
    )
    op.execute(
        """
        create table messages (
            id         uuid primary key default gen_random_uuid(),
            session_id uuid not null references sessions (id) on delete cascade,
            guest_id   uuid not null references guests (id) on delete cascade,
            role       text not null check (role in ('user', 'assistant')),
            content    text not null,
            created_at timestamptz not null default now()
        )
        """
    )
    op.execute("create index messages_session_created_idx on messages (session_id, created_at desc)")
    op.execute("create index messages_guest_idx on messages (guest_id)")
    op.execute(
        """
        create table feedback (
            id         uuid primary key default gen_random_uuid(),
            guest_id   uuid not null references guests (id) on delete cascade,
            session_id uuid not null,
            message_id uuid not null unique,
            thumb      text not null check (thumb in ('up', 'down')),
            comment    text check (comment is null or char_length(comment) <= 2000),
            created_at timestamptz not null default now(),
            updated_at timestamptz not null default now()
        )
        """
    )
    op.execute("create index feedback_guest_idx on feedback (guest_id)")
    op.execute(
        """
        create table events (
            id         bigint generated always as identity primary key,
            guest_id   uuid not null references guests (id) on delete cascade,
            session_id uuid,
            type       text not null
                       check (type in ('session_started', 'recommendation_shown', 'route_drawn')),
            created_at timestamptz not null default now()
        )
        """
    )
    op.execute(
        "create unique index events_session_type_key on events (session_id, type) "
        "where session_id is not null"
    )
    op.execute("create index events_type_created_idx on events (type, created_at)")
    op.execute("create index events_guest_idx on events (guest_id)")

    tables = ", ".join(GRANTS)
    op.execute(f"revoke all on {tables} from public")
    for table, commands in GRANTS.items():
        op.execute(f"grant {', '.join(commands)} on {table} to {app}")
        op.execute(f"alter table {table} enable row level security")
        for command in commands:
            check = {
                "select": "using (true)",
                "delete": "using (true)",
                "insert": "with check (true)",
                "update": "using (true) with check (true)",
            }[command]
            op.execute(f"create policy {table}_app_{command} on {table} for {command} to {app} {check}")


def downgrade() -> None:
    # destructive on purpose: guest data cannot exist without these tables
    for table in ("events", "feedback", "messages", "sessions", "guests"):
        op.execute(f"drop table {table}")
```

- [ ] **Step 2: Rehearse on the local database**

Run: `./backend/script.demo.local.sh --local migrate upgrade head`
Expected: output ends with `Running upgrade 0003 -> 0004`.

Run: `./backend/script.demo.local.sh --local migrate downgrade -1 && ./backend/script.demo.local.sh --local migrate upgrade head`
Expected: both succeed (the downgrade/upgrade round trip works).

- [ ] **Step 3: Extend `cmd_verify`** in `backend/script.demo.local.sh` (git-ignored). Replace the `WANT = {...}` block with:

```python
APP, WORKER = os.environ["DEMO_APP_ROLE"], os.environ["DEMO_WORKER_ROLE"]
WANT = {
    APP: {
        "facilities": {"SELECT"}, "wait_times": {"SELECT"},
        "guests": {"SELECT", "INSERT", "UPDATE"},
        "sessions": {"SELECT", "INSERT", "UPDATE", "DELETE"},
        "messages": {"SELECT", "INSERT"},
        "feedback": {"SELECT", "INSERT", "UPDATE"},
        "events": {"SELECT", "INSERT"},
    },
    WORKER: {
        "facilities": {"SELECT", "INSERT"}, "wait_times": {"SELECT", "INSERT", "UPDATE"},
        "guests": set(), "sessions": set(), "messages": set(), "feedback": set(), "events": set(),
    },
}
```

and change the RLS loop's tuple to
`("facilities", "wait_times", "guests", "sessions", "messages", "feedback", "events")`.

- [ ] **Step 4: Verify locally**

Run: `./backend/script.demo.local.sh --local roles && ./backend/script.demo.local.sh --local verify`
Expected: every line starts with `PASS` (22 lines), exit code 0.

- [ ] **Step 5: Apply to the remote demo database** — ask the user for the go-ahead and for the tunnel on 127.0.0.1:5435 first.

Run: `./backend/script.demo.local.sh status` → `tunnel : reachable`, revision `0003`.
Run: `./backend/script.demo.local.sh migrate upgrade head` → check the printed `alembic target:` line names the Railway database, confirm, expect `0003 -> 0004`.
Run: `./backend/script.demo.local.sh verify` → all `PASS`.

- [ ] **Step 6: Commit** (after approval)

```bash
git add migrations/postgres/versions/20261007_0004_guest_tables.py
git commit -m "feat: add guest tables migration with app-role grants and rls"
```

---

### Task 3: `config.py`, `demo_db.py`, lifespan and health

**Files:**
- Create: `backend/config.py`, `backend/demo_db.py`
- Modify: `backend/main.py` (lifespan, `/health`), `backend/requirements.txt`
- Test: `backend/tests/test_config.py`, `backend/tests/test_health.py` (append)

**Interfaces:**
- Produces: `config.demo_mode() -> bool`; `config.DOWNTOWN_TORONTO: dict[str, float]`; `config.starter_prompts() -> list[str]`; `config.internal_token() -> str`.
- Produces: `demo_db.fetch_all(sql: str, params: Sequence | Mapping = ()) -> list[dict]`, `demo_db.fetch_one(...) -> dict | None`, `demo_db.execute(...) -> int` (row count), `demo_db.open_pool() -> None`, `demo_db.close_pool() -> None`.

- [ ] **Step 1: Write the failing test** — `backend/tests/test_config.py`:

```python
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

import config


@pytest.mark.parametrize("value,expected", [("true", True), ("TRUE", True), ("1", True),
                                            ("false", False), ("", False), ("yes", False)])
def test_demo_mode_reads_env_each_call(monkeypatch: pytest.MonkeyPatch, value: str, expected: bool) -> None:
    monkeypatch.setenv("DEMO_MODE", value)
    assert config.demo_mode() is expected


def test_demo_mode_defaults_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEMO_MODE", raising=False)
    assert config.demo_mode() is False


def test_starter_prompts_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEMO_STARTER_PROMPTS", '["one", "two"]')
    assert config.starter_prompts() == ["one", "two"]


@pytest.mark.parametrize("bad", ["not json", '{"a": 1}', "[]", '[1, 2]', '["ok", ""]'])
def test_starter_prompts_fall_back_on_bad_env(monkeypatch: pytest.MonkeyPatch, bad: str) -> None:
    monkeypatch.setenv("DEMO_STARTER_PROMPTS", bad)
    assert config.starter_prompts() == config.DEFAULT_STARTER_PROMPTS
```

- [ ] **Step 2: Run it to see it fail**

Run: `cd backend && doppler run -- python -m pytest tests/test_config.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'config'`.

- [ ] **Step 3: Write `backend/config.py`**

```python
"""Demo-mode switch and constants. Read through functions so tests can flip the environment."""
import json
import os

DOWNTOWN_TORONTO: dict[str, float] = {"lat": 43.6532, "lng": -79.3832}
ALL_MODES: list[str] = ["car", "bike", "bus", "walk"]
DEMO_MODES: list[str] = ["car"]  # bike/bus/walk ETAs are multipliers, not routes (sprint 2)

DEFAULT_STARTER_PROMPTS: list[str] = [
    "I have a fever and sore throat",
    "Chest pain and shortness of breath",
    "Twisted my ankle — it's swollen",
]


def demo_mode() -> bool:
    return os.environ.get("DEMO_MODE", "").strip().lower() in ("1", "true")


def starter_prompts() -> list[str]:
    raw = os.environ.get("DEMO_STARTER_PROMPTS", "").strip()
    if not raw:
        return DEFAULT_STARTER_PROMPTS
    try:
        parsed = json.loads(raw)
    except ValueError:
        return DEFAULT_STARTER_PROMPTS
    if not isinstance(parsed, list) or not parsed:
        return DEFAULT_STARTER_PROMPTS
    if not all(isinstance(p, str) and p.strip() for p in parsed):
        return DEFAULT_STARTER_PROMPTS
    return parsed


def internal_token() -> str:
    return os.environ.get("DEMO_INTERNAL_TOKEN", "").strip()
```

- [ ] **Step 4: Write `backend/demo_db.py`**

```python
"""Connection pool for the demo Postgres (role medicoord_app, POSTGRES_DB_URL_APP).

Only services/guest_store.py and the demo branches of services/facilities.py and
services/wait_times.py import this. Every call takes a connection for one statement; the
`with pool.connection()` block commits on success and rolls back on error.
"""
import os
from collections.abc import Mapping, Sequence
from typing import Any

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

Params = Sequence[Any] | Mapping[str, Any]

_pool: ConnectionPool | None = None


def _conninfo() -> str:
    raw = os.environ["POSTGRES_DB_URL_APP"].strip()
    return raw.replace("postgresql+psycopg://", "postgresql://", 1)


def open_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            _conninfo(),
            min_size=1,
            max_size=5,
            timeout=5,  # seconds to wait for a free connection
            kwargs={"row_factory": dict_row, "options": "-c statement_timeout=5000"},
            open=True,
        )
    return _pool


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


def fetch_all(sql: str, params: Params = ()) -> list[dict[str, Any]]:
    with open_pool().connection() as conn:
        return conn.execute(sql, params).fetchall()


def fetch_one(sql: str, params: Params = ()) -> dict[str, Any] | None:
    with open_pool().connection() as conn:
        return conn.execute(sql, params).fetchone()


def execute(sql: str, params: Params = ()) -> int:
    with open_pool().connection() as conn:
        return conn.execute(sql, params).rowcount
```

- [ ] **Step 5: Add the dependency** — append to `backend/requirements.txt`:

```
psycopg_pool==3.*
```

Run: `pip install "psycopg_pool==3.*"`

- [ ] **Step 6: Wire lifespan and health in `backend/main.py`** — add imports:

```python
import demo_db
from config import demo_mode
```

In `lifespan`, before the `try:` that warms the cache:

```python
    if demo_mode():
        try:
            demo_db.open_pool()
        except Exception as exc:
            logger.warning("demo_db_pool_open_failed", extra={"error_type": type(exc).__name__})
```

and after `close_graph_provider()`:

```python
    demo_db.close_pool()
```

In `health()`, before `return result`:

```python
    result["demoMode"] = demo_mode()
    if demo_mode():
        try:
            demo_db.fetch_one("select 1 as ok")
            result["demoDb"] = "ok"
        except Exception as exc:
            result["demoDb"] = "unreachable"
            logger.warning("demo_db_health_failed", extra={"error_type": type(exc).__name__})
```

- [ ] **Step 7: Add the health test** — append to `backend/tests/test_health.py`:

```python
def test_health_reports_demo_db_unreachable(monkeypatch):
    import main
    monkeypatch.setenv("DEMO_MODE", "true")

    def boom(*_args, **_kwargs):
        raise RuntimeError("down")

    monkeypatch.setattr(main.demo_db, "fetch_one", boom)
    body = main.health()
    assert body["demoMode"] is True and body["demoDb"] == "unreachable"


def test_health_omits_demo_db_when_flag_off(monkeypatch):
    import main
    monkeypatch.delenv("DEMO_MODE", raising=False)
    body = main.health()
    assert body["demoMode"] is False and "demoDb" not in body
```

- [ ] **Step 8: Run the tests**

Run: `cd backend && doppler run -- python -m pytest tests/test_config.py tests/test_health.py -q`
Expected: PASS.

- [ ] **Step 9: Commit** (after approval)

```bash
git add backend/config.py backend/demo_db.py backend/main.py backend/requirements.txt backend/tests/test_config.py backend/tests/test_health.py
git commit -m "feat: add demo mode switch and demo postgres pool"
```

---

### Task 4: `services/guest_store.py`

**Files:**
- Create: `backend/services/guest_store.py`
- Test: `backend/tests/test_guest_store.py`

**Interfaces:**
- Consumes: `demo_db.fetch_all / fetch_one / execute`.
- Produces:
  - `touch_guest(guest_id: str, internal: bool) -> bool` — True when the guest row was just created.
  - `create_session(guest_id: str, title: str) -> dict` — keys `id, user_id, title, created_at, updated_at`.
  - `add_message(session_id: str, guest_id: str, role: str, content: str) -> dict` — keys `id, session_id, user_id, role, content, created_at`; raises `SessionNotFound`.
  - `get_past_conversations(guest_id: str, session_limit: int = 5, message_limit: int = 20) -> tuple[list[dict], dict[str, list[dict]]]`
  - `get_older_messages(guest_id: str, session_id: str, before_id: str, limit: int = 20) -> list[dict]`
  - `upsert_feedback(guest_id: str, session_id: str, message_id: str, thumb: str, comment: str | None) -> bool`
  - `record_event(guest_id: str, event_type: str, session_id: str) -> bool` — False when the session is not the guest's.
  - `purge_expired_sessions() -> int`
  - `class SessionNotFound(LookupError)`

- [ ] **Step 1: Write the failing tests** — `backend/tests/test_guest_store.py`:

```python
"""guest_store against the local rehearsal DB (docker medicoord-demo-pg, revision 0004).

Never touches the remote database: POSTGRES_DB_URL_APP is forced to the local DSN.
Skipped when the container is not running.
"""
import os
import sys
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import psycopg
import pytest

import demo_db
from services import guest_store

LOCAL_DSN = "postgresql://postgres:postgres@localhost:5433/medicoord_demo"


@pytest.fixture()
def guest(monkeypatch: pytest.MonkeyPatch):
    try:
        admin = psycopg.connect(LOCAL_DSN, connect_timeout=3, autocommit=True)
    except psycopg.OperationalError:
        pytest.skip("local rehearsal DB not running")
    monkeypatch.setenv("POSTGRES_DB_URL_APP", LOCAL_DSN)
    demo_db.close_pool()
    created: list[str] = []

    def make() -> str:
        gid = str(uuid.uuid4())
        guest_store.touch_guest(gid, internal=False)
        created.append(gid)
        return gid

    yield make
    demo_db.close_pool()
    admin.execute("delete from guests where id = any(%s::uuid[])", (created,))
    admin.execute("delete from sessions where title like 'pytest-%'")
    admin.close()


def test_touch_guest_reports_creation_once(guest) -> None:
    gid = str(uuid.uuid4())
    try:
        assert guest_store.touch_guest(gid, internal=False) is True
        assert guest_store.touch_guest(gid, internal=False) is False
    finally:
        with psycopg.connect(LOCAL_DSN, autocommit=True) as admin:
            admin.execute("delete from guests where id = %s", (gid,))


def test_internal_flag_sticks_once_set(guest) -> None:
    gid = guest()
    guest_store.touch_guest(gid, internal=True)
    guest_store.touch_guest(gid, internal=False)
    row = demo_db.fetch_one("select is_internal from guests where id = %s", (gid,))
    assert row == {"is_internal": True}


def test_session_and_messages_round_trip_with_string_ids(guest) -> None:
    gid = guest()
    session = guest_store.create_session(gid, "pytest-fever")
    assert session["user_id"] == gid and isinstance(session["id"], str)

    user_msg = guest_store.add_message(session["id"], gid, "user", "I have a fever")
    guest_store.add_message(session["id"], gid, "assistant", "How long?")
    assert user_msg["user_id"] == gid and user_msg["session_id"] == session["id"]

    sessions, messages = guest_store.get_past_conversations(gid)
    assert [s["id"] for s in sessions] == [session["id"]]
    assert [m["content"] for m in messages[session["id"]]] == ["I have a fever", "How long?"]


def test_add_message_rejects_foreign_session(guest) -> None:
    owner, intruder = guest(), guest()
    session = guest_store.create_session(owner, "pytest-private")
    with pytest.raises(guest_store.SessionNotFound):
        guest_store.add_message(session["id"], intruder, "user", "let me in")
    assert demo_db.fetch_one("select count(*) as n from messages where session_id = %s",
                             (session["id"],)) == {"n": 0}


@pytest.mark.parametrize("bad", ["", "abc", "1; drop table guests", "00000000-0000"])
def test_add_message_bad_session_id_is_not_found(guest, bad: str) -> None:
    with pytest.raises(guest_store.SessionNotFound):
        guest_store.add_message(bad, guest(), "user", "x")


def test_past_conversations_only_returns_own_sessions(guest) -> None:
    a, b = guest(), guest()
    guest_store.create_session(a, "pytest-a")
    assert guest_store.get_past_conversations(b) == ([], {})


def test_message_limit_keeps_the_newest_in_order(guest) -> None:
    gid = guest()
    session = guest_store.create_session(gid, "pytest-limit")
    for i in range(5):
        guest_store.add_message(session["id"], gid, "user", f"m{i}")
    _, messages = guest_store.get_past_conversations(gid, message_limit=2)
    assert [m["content"] for m in messages[session["id"]]] == ["m3", "m4"]


def test_older_messages_are_paginated_and_owned(guest) -> None:
    owner, intruder = guest(), guest()
    session = guest_store.create_session(owner, "pytest-older")
    ids = [guest_store.add_message(session["id"], owner, "user", f"m{i}")["id"] for i in range(3)]
    older = guest_store.get_older_messages(owner, session["id"], ids[2])
    assert [m["content"] for m in older] == ["m0", "m1"]
    assert guest_store.get_older_messages(intruder, session["id"], ids[2]) == []


def test_older_messages_bad_uuid_is_empty(guest) -> None:
    assert guest_store.get_older_messages(guest(), "nope", "nope") == []


def test_feedback_upserts_one_row_per_message(guest) -> None:
    gid = guest()
    session = guest_store.create_session(gid, "pytest-feedback")
    guest_store.add_message(session["id"], gid, "user", "hi")
    reply = guest_store.add_message(session["id"], gid, "assistant", "Go to X")

    assert guest_store.upsert_feedback(gid, session["id"], reply["id"], "up", None) is True
    assert guest_store.upsert_feedback(gid, session["id"], reply["id"], "down", "wrong place") is True
    rows = demo_db.fetch_all("select thumb, comment from feedback where message_id = %s", (reply["id"],))
    assert rows == [{"thumb": "down", "comment": "wrong place"}]


def test_feedback_rejects_foreign_message(guest) -> None:
    owner, intruder = guest(), guest()
    session = guest_store.create_session(owner, "pytest-fb-foreign")
    reply = guest_store.add_message(session["id"], owner, "assistant", "Go to X")
    assert guest_store.upsert_feedback(intruder, session["id"], reply["id"], "up", None) is False


def test_feedback_rejects_user_messages(guest) -> None:
    gid = guest()
    session = guest_store.create_session(gid, "pytest-fb-user")
    msg = guest_store.add_message(session["id"], gid, "user", "hi")
    assert guest_store.upsert_feedback(gid, session["id"], msg["id"], "up", None) is False


def test_event_is_recorded_once_per_session_and_type(guest) -> None:
    gid = guest()
    session = guest_store.create_session(gid, "pytest-event")
    assert guest_store.record_event(gid, "route_drawn", session["id"]) is True
    assert guest_store.record_event(gid, "route_drawn", session["id"]) is True
    assert demo_db.fetch_one("select count(*) as n from events where session_id = %s",
                             (session["id"],)) == {"n": 1}


def test_event_rejects_foreign_session(guest) -> None:
    owner, intruder = guest(), guest()
    session = guest_store.create_session(owner, "pytest-event-foreign")
    assert guest_store.record_event(intruder, "route_drawn", session["id"]) is False


def test_purge_deletes_sessions_older_than_30_days_and_keeps_feedback(guest) -> None:
    gid = guest()
    old = guest_store.create_session(gid, "pytest-old")
    new = guest_store.create_session(gid, "pytest-new")
    reply = guest_store.add_message(old["id"], gid, "assistant", "Go to X")
    guest_store.upsert_feedback(gid, old["id"], reply["id"], "up", None)
    with psycopg.connect(LOCAL_DSN, autocommit=True) as admin:
        admin.execute("update sessions set created_at = now() - interval '31 days' where id = %s", (old["id"],))

    assert guest_store.purge_expired_sessions() >= 1

    remaining = demo_db.fetch_all("select id::text as id from sessions where guest_id = %s", (gid,))
    assert remaining == [{"id": new["id"]}]
    assert demo_db.fetch_one("select count(*) as n from messages where session_id = %s", (old["id"],)) == {"n": 0}
    assert demo_db.fetch_one("select count(*) as n from feedback where message_id = %s", (reply["id"],)) == {"n": 1}
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd backend && doppler run -- python -m pytest tests/test_guest_store.py -q`
Expected: FAIL with `ImportError: cannot import name 'guest_store'` (or all SKIPPED if the container is down — start it: `docker start medicoord-demo-pg`).

- [ ] **Step 3: Write `backend/services/guest_store.py`**

```python
"""All SQL for guest data in the demo Postgres.

Every statement that touches a session or a message carries the guest id: the backend connects
as one database role, so this module is what keeps one guest out of another guest's data.
Ids are returned as text and `guest_id` is exposed as `user_id`, so rows match the API contract
(`Session` / `Message` in shared/types.ts) the Supabase path already serves.
"""
from uuid import UUID

import demo_db

SESSION_COLUMNS = "id::text as id, guest_id::text as user_id, title, created_at, updated_at"
MESSAGE_COLUMNS = (
    "id::text as id, session_id::text as session_id, guest_id::text as user_id, "
    "role, content, created_at"
)
RETENTION_DAYS = 30


class SessionNotFound(LookupError):
    """The session does not exist or belongs to another guest."""


def _is_uuid(value: str) -> bool:
    try:
        UUID(str(value))
    except ValueError:
        return False
    return True


def touch_guest(guest_id: str, internal: bool) -> bool:
    row = demo_db.fetch_one(
        """
        insert into guests (id, is_internal) values (%s, %s)
        on conflict (id) do update
            set last_seen_at = now(),
                is_internal = guests.is_internal or excluded.is_internal
        returning (xmax = 0) as created
        """,
        (guest_id, internal),
    )
    return bool(row and row["created"])


def create_session(guest_id: str, title: str) -> dict:
    row = demo_db.fetch_one(
        f"insert into sessions (guest_id, title) values (%s, %s) returning {SESSION_COLUMNS}",
        (guest_id, title),
    )
    assert row is not None  # insert ... returning always yields the row
    return row


def add_message(session_id: str, guest_id: str, role: str, content: str) -> dict:
    if not _is_uuid(session_id):
        raise SessionNotFound(session_id)
    # one statement: the insert happens only if the session belongs to this guest
    row = demo_db.fetch_one(
        f"""
        with owned as (
            update sessions set updated_at = now()
            where id = %s and guest_id = %s
            returning id
        )
        insert into messages (session_id, guest_id, role, content)
        select id, %s, %s, %s from owned
        returning {MESSAGE_COLUMNS}
        """,
        (session_id, guest_id, guest_id, role, content),
    )
    if row is None:
        raise SessionNotFound(session_id)
    return row


def get_past_conversations(
    guest_id: str, session_limit: int = 5, message_limit: int = 20
) -> tuple[list[dict], dict[str, list[dict]]]:
    sessions = demo_db.fetch_all(
        f"select {SESSION_COLUMNS} from sessions where guest_id = %s "
        "order by updated_at desc limit %s",
        (guest_id, session_limit),
    )
    if not sessions:
        return [], {}

    session_ids = [s["id"] for s in sessions]
    rows = demo_db.fetch_all(
        f"""
        select id, session_id, user_id, role, content, created_at from (
            select {MESSAGE_COLUMNS},
                   row_number() over (partition by session_id order by created_at desc) as rn
            from messages
            where session_id = any(%s::uuid[]) and guest_id = %s
        ) newest
        where rn <= %s
        order by created_at
        """,
        (session_ids, guest_id, message_limit),
    )
    messages: dict[str, list[dict]] = {sid: [] for sid in session_ids}
    for row in rows:
        messages[row["session_id"]].append(row)
    return sessions, messages


def get_older_messages(guest_id: str, session_id: str, before_id: str, limit: int = 20) -> list[dict]:
    if not (_is_uuid(session_id) and _is_uuid(before_id)):
        return []
    rows = demo_db.fetch_all(
        f"""
        select {MESSAGE_COLUMNS} from messages
        where session_id = %s and guest_id = %s
          and created_at < (select created_at from messages where id = %s and guest_id = %s)
        order by created_at desc
        limit %s
        """,
        (session_id, guest_id, before_id, guest_id, limit),
    )
    return list(reversed(rows))


def upsert_feedback(guest_id: str, session_id: str, message_id: str, thumb: str, comment: str | None) -> bool:
    written = demo_db.execute(
        """
        insert into feedback (guest_id, session_id, message_id, thumb, comment)
        select guest_id, session_id, id, %s, %s from messages
        where id = %s and session_id = %s and guest_id = %s and role = 'assistant'
        on conflict (message_id) do update
            set thumb = excluded.thumb, comment = excluded.comment, updated_at = now()
        """,
        (thumb, comment, message_id, session_id, guest_id),
    )
    return written > 0


def record_event(guest_id: str, event_type: str, session_id: str) -> bool:
    if not _is_uuid(session_id):
        return False
    owned = demo_db.fetch_one(
        "select 1 as ok from sessions where id = %s and guest_id = %s", (session_id, guest_id)
    )
    if owned is None:
        return False
    demo_db.execute(
        """
        insert into events (guest_id, session_id, type) values (%s, %s, %s)
        on conflict (session_id, type) where session_id is not null do nothing
        """,
        (guest_id, session_id, event_type),
    )
    return True


def purge_expired_sessions() -> int:
    """Chat text retention: a session (title and messages) lives 30 days from its creation."""
    return demo_db.execute(
        "delete from sessions where created_at < now() - make_interval(days => %s)", (RETENTION_DAYS,)
    )
```

- [ ] **Step 4: Run the tests**

Run: `cd backend && doppler run -- python -m pytest tests/test_guest_store.py -q`
Expected: 18 passed (not skipped — if skipped, start the container and re-run).

- [ ] **Step 5: Commit** (after approval)

```bash
git add backend/services/guest_store.py backend/tests/test_guest_store.py
git commit -m "feat: add guest store for demo sessions, messages, feedback and events"
```

---

### Task 5: `get_actor` dependency and CORS

**Files:**
- Modify: `backend/middleware/auth.py`, `backend/main.py` (CORS)
- Test: `backend/tests/test_actor.py`

**Interfaces:**
- Consumes: `config.demo_mode()`, `config.internal_token()`, `guest_store.touch_guest`, `services.retention.purge_if_due` (created in Task 8; this task adds a stub call guarded by import inside the function).
- Produces: `middleware.auth.get_actor(request: Request, authorization: str = Header(default="")) -> object` — the returned object has `.id: str`, `.email: str | None`, `.is_guest: bool`. Non-guest users get `is_guest = False`.

- [ ] **Step 1: Write the failing tests** — `backend/tests/test_actor.py`:

```python
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import patch

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

import middleware.auth as auth

GUEST = "3f2b1c9e-8a47-4d1e-9c55-0a1b2c3d4e5f"


def _client() -> TestClient:
    app = FastAPI()

    @app.get("/who")
    async def who(actor: object = Depends(auth.get_actor)) -> dict:
        return {"id": str(actor.id), "is_guest": actor.is_guest}  # type: ignore[attr-defined]

    return TestClient(app)


@pytest.fixture()
def demo(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.setenv("DEMO_INTERNAL_TOKEN", "s3cret")
    with patch.object(auth.guest_store, "touch_guest", return_value=False) as touch, \
         patch.object(auth, "purge_if_due") as purge:
        yield touch, purge


def test_guest_header_becomes_actor(demo) -> None:
    touch, _ = demo
    resp = _client().get("/who", headers={"X-Guest-Id": GUEST})
    assert resp.status_code == 200 and resp.json() == {"id": GUEST, "is_guest": True}
    touch.assert_called_once_with(GUEST, False)


@pytest.mark.parametrize("bad", ["", "abc", "1; drop table guests", "null"])
def test_guest_header_malformed_is_400(demo, bad: str) -> None:
    touch, _ = demo
    headers = {"X-Guest-Id": bad} if bad else {}
    assert _client().get("/who", headers=headers).status_code == 400
    touch.assert_not_called()


def test_guest_id_is_normalised_to_canonical_form(demo) -> None:
    resp = _client().get("/who", headers={"X-Guest-Id": GUEST.upper()})
    assert resp.json()["id"] == GUEST


def test_internal_token_marks_guest_internal(demo) -> None:
    touch, _ = demo
    _client().get("/who", headers={"X-Guest-Id": GUEST, "X-Internal": "s3cret"})
    touch.assert_called_once_with(GUEST, True)


def test_wrong_or_unset_internal_token_does_not_mark(demo, monkeypatch: pytest.MonkeyPatch) -> None:
    touch, _ = demo
    _client().get("/who", headers={"X-Guest-Id": GUEST, "X-Internal": "nope"})
    touch.assert_called_once_with(GUEST, False)
    touch.reset_mock()
    monkeypatch.setenv("DEMO_INTERNAL_TOKEN", "")
    _client().get("/who", headers={"X-Guest-Id": GUEST, "X-Internal": ""})
    touch.assert_called_once_with(GUEST, False)


def test_new_guest_triggers_purge_check(demo) -> None:
    touch, purge = demo
    touch.return_value = True
    _client().get("/who", headers={"X-Guest-Id": GUEST})
    purge.assert_called_once_with()


def test_database_failure_is_503(demo) -> None:
    touch, _ = demo
    touch.side_effect = RuntimeError("pool timeout")
    assert _client().get("/who", headers={"X-Guest-Id": GUEST}).status_code == 503


def test_flag_off_requires_bearer_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEMO_MODE", raising=False)
    assert _client().get("/who", headers={"X-Guest-Id": GUEST}).status_code == 401


def test_flag_off_uses_supabase_user(monkeypatch: pytest.MonkeyPatch) -> None:
    import types
    monkeypatch.delenv("DEMO_MODE", raising=False)
    user = types.SimpleNamespace(id="u-1", email="a@b.c")
    with patch.object(auth, "verify_token", return_value=user):
        resp = _client().get("/who", headers={"Authorization": "Bearer t"})
    assert resp.json() == {"id": "u-1", "is_guest": False}


def test_cors_allows_guest_headers() -> None:
    import main
    resp = TestClient(main.app).options(
        "/chat/sessions",
        headers={
            "Origin": main.ALLOWED_ORIGINS[0],
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "x-guest-id,x-internal",
        },
    )
    allowed = resp.headers.get("access-control-allow-headers", "").lower()
    assert resp.status_code == 200 and "x-guest-id" in allowed and "x-internal" in allowed
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd backend && doppler run -- python -m pytest tests/test_actor.py -q`
Expected: FAIL with `AttributeError: module 'middleware.auth' has no attribute 'get_actor'`.

- [ ] **Step 3: Create the purge stub so the import resolves** — `backend/services/retention.py` (Task 8 replaces the body):

```python
def purge_if_due() -> None:
    """Replaced in Task 8."""
```

- [ ] **Step 4: Add `get_actor` to `backend/middleware/auth.py`** — add imports at the top:

```python
import hmac
import types
from uuid import UUID

from starlette.concurrency import run_in_threadpool

from config import demo_mode, internal_token
from services import guest_store
from services.retention import purge_if_due
```

and add after `get_current_user`:

```python
def _is_internal(header_value: str) -> bool:
    expected = internal_token()
    return bool(expected) and hmac.compare_digest(header_value.encode(), expected.encode())


async def get_actor(request: Request, authorization: str = Header(default="")) -> object:
    """Who is calling: a guest (DEMO_MODE) or a Supabase user. Exposes .id, .email, .is_guest."""
    if not demo_mode():
        user = await get_current_user(authorization)
        return types.SimpleNamespace(id=user.id, email=user.email, is_guest=False)  # type: ignore[attr-defined]

    try:
        guest_id = str(UUID(request.headers.get("X-Guest-Id", "")))
    except ValueError:
        raise HTTPException(400, "Missing or malformed X-Guest-Id header") from None

    internal = _is_internal(request.headers.get("X-Internal", ""))
    try:
        created = await run_in_threadpool(guest_store.touch_guest, guest_id, internal)
    except Exception as exc:
        logger.error("guest_touch_failed", extra={"error_type": type(exc).__name__})
        raise HTTPException(503, "Database unavailable") from exc
    if created:
        await run_in_threadpool(purge_if_due)

    request.state.guest_id = guest_id
    return types.SimpleNamespace(id=guest_id, email=None, is_guest=True)
```

- [ ] **Step 5: Allow the headers in CORS** — in `backend/main.py` replace the `allow_headers` line with:

```python
    allow_headers=["Content-Type", "Authorization", "X-Request-ID", "If-None-Match", "X-Guest-Id", "X-Internal"],
```

- [ ] **Step 6: Run the tests**

Run: `cd backend && doppler run -- python -m pytest tests/test_actor.py tests/test_auth_middleware.py -q`
Expected: PASS.

- [ ] **Step 7: Commit** (after approval)

```bash
git add backend/middleware/auth.py backend/main.py backend/services/retention.py backend/tests/test_actor.py
git commit -m "feat: resolve guests from X-Guest-Id under demo mode"
```

---

### Task 6: Demo branches in `facilities`, `wait_times`, `chat`; wait details in `/facilities`

**Files:**
- Modify: `backend/services/facilities.py`, `backend/services/wait_times.py`, `backend/services/chat.py`, `backend/main.py`
- Modify: `backend/tests/test_facilities_routes.py`
- Test: `backend/tests/test_demo_services.py`

**Interfaces:**
- Consumes: `demo_db.fetch_all`, `guest_store.*`, `config.demo_mode()`.
- Produces:
  - `services.wait_times.get_wait_map() -> dict[str, dict]` — values `{"wait_minutes": int | None, "raw_wait": str | None, "predicted": bool}`.
  - `services.wait_times.get_wait_minutes_map() -> dict[str, int | None]` — unchanged signature, now derived from `get_wait_map()`.
  - `services.facilities.annotate_wait_details(records: list[dict], id_key: str, wait_map: dict[str, dict]) -> list[dict]`.
  - `services.chat.get_older_messages(session_id: str, before_id: str, limit: int = 20, user_id: str | None = None) -> list`.

- [ ] **Step 1: Write the failing tests** — `backend/tests/test_demo_services.py`:

```python
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import patch

import pytest

from services import chat, facilities, wait_times


@pytest.fixture()
def demo(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEMO_MODE", "true")


# ── wait times ────────────────────────────────────────────────────────────────

@patch("services.wait_times.redis_client")
def test_wait_map_reads_predicted_ranges_from_redis(mock_redis) -> None:
    mock_redis.hgetall.return_value = {
        "live": json.dumps({"wait_minutes": 42, "raw_wait": "42 min", "predicted": False}),
        "pred": json.dumps({"wait_minutes": None, "raw_wait": "45m–2h", "predicted": True}),
        "old":  json.dumps({"wait_minutes": 10}),  # written by the old worker: no flags
    }
    assert wait_times.get_wait_map() == {
        "live": {"wait_minutes": 42, "raw_wait": "42 min", "predicted": False},
        "pred": {"wait_minutes": None, "raw_wait": "45m–2h", "predicted": True},
        "old":  {"wait_minutes": 10, "raw_wait": None, "predicted": False},
    }
    assert wait_times.get_wait_minutes_map() == {"live": 42, "pred": None, "old": 10}


@patch("services.wait_times.supabase_rpc")
@patch("services.wait_times.demo_db")
@patch("services.wait_times.redis_client")
def test_demo_fallback_reads_the_table_not_supabase(mock_redis, mock_db, mock_rpc, demo) -> None:
    mock_redis.hgetall.return_value = {}
    mock_db.fetch_all.return_value = [
        {"facility_id": "h1", "wait_minutes": None, "raw_wait": "1h–3h", "predicted": True,
         "source": "erstat", "recorded_at": None},
    ]
    assert wait_times.get_wait_map() == {"h1": {"wait_minutes": None, "raw_wait": "1h–3h", "predicted": True}}
    mock_rpc.assert_not_called()


# ── facilities ────────────────────────────────────────────────────────────────

@patch("services.facilities.demo_db")
def test_demo_facilities_come_from_postgres_with_parsed_hours(mock_db, demo) -> None:
    mock_db.fetch_all.return_value = [
        {"id": "f1", "name": "A", "category": "hospital", "weekday_hours": '["24/7"]'},
        {"id": "f2", "name": "B", "category": "ambulatory", "weekday_hours": None},
    ]
    rows = facilities.get_all_facilities(category="hospital", severity="urgent")
    assert [r["weekday_hours"] for r in rows] == [["24/7"], []]
    sql, params = mock_db.fetch_all.call_args.args
    assert "is_operational" in sql and params == {"category": "hospital", "severity": "urgent"}


@patch("services.facilities.demo_db")
def test_demo_facilities_db_error_is_503(mock_db, demo) -> None:
    from fastapi import HTTPException
    mock_db.fetch_all.side_effect = RuntimeError("down")
    with pytest.raises(HTTPException) as err:
        facilities.get_all_facilities()
    assert err.value.status_code == 503


def test_annotate_wait_details_adds_fields_without_mutating() -> None:
    records = [{"id": "a"}, {"id": "b"}]
    out = facilities.annotate_wait_details(
        records, "id", {"a": {"wait_minutes": None, "raw_wait": "45m–2h", "predicted": True}})
    assert out == [{"id": "a", "raw_wait": "45m–2h", "predicted": True},
                   {"id": "b", "raw_wait": None, "predicted": False}]
    assert records == [{"id": "a"}, {"id": "b"}]


# ── chat ──────────────────────────────────────────────────────────────────────

@patch("services.chat.supabase_insert")
@patch("services.chat.guest_store")
def test_chat_uses_guest_store_in_demo_mode(mock_store, mock_insert, demo) -> None:
    mock_store.create_session.return_value = {"id": "s1"}
    assert chat.create_session("g1", "title") == {"id": "s1"}
    chat.add_message("s1", "g1", "user", "hi")
    chat.get_past_conversations("g1")
    chat.get_older_messages("s1", "m1", user_id="g1")
    mock_store.add_message.assert_called_once_with("s1", "g1", "user", "hi")
    mock_store.get_past_conversations.assert_called_once_with("g1", 5, 20)
    mock_store.get_older_messages.assert_called_once_with("g1", "s1", "m1", 20)
    mock_insert.assert_not_called()


@patch("services.chat.supabase_insert", return_value=[{"id": "s1"}])
@patch("services.chat.guest_store")
def test_chat_uses_supabase_when_flag_off(mock_store, mock_insert, monkeypatch) -> None:
    monkeypatch.delenv("DEMO_MODE", raising=False)
    chat.create_session("u1", "title")
    mock_insert.assert_called_once()
    mock_store.create_session.assert_not_called()
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd backend && doppler run -- python -m pytest tests/test_demo_services.py -q`
Expected: FAIL with `AttributeError: module 'services.wait_times' has no attribute 'get_wait_map'`.

- [ ] **Step 3: Rewrite the read side of `backend/services/wait_times.py`** — add imports `import demo_db` and `from config import demo_mode`, then replace the whole `get_wait_minutes_map` function with:

```python
def _wait_info(entry: dict) -> dict:
    return {
        "wait_minutes": entry.get("wait_minutes"),
        "raw_wait": entry.get("raw_wait"),
        "predicted": bool(entry.get("predicted", False)),
    }


def _fallback_rows() -> list[dict]:
    """Current wait rows from the database of record: demo Postgres, or the Supabase RPC."""
    if demo_mode():
        return demo_db.fetch_all(
            "select facility_id::text as facility_id, wait_minutes, raw_wait, predicted, "
            "source, recorded_at from wait_times"
        )
    return supabase_rpc("latest_wait_times", {})


def get_wait_map() -> dict[str, dict]:
    """
    Cache-aside read of current ER waits, keyed by facility_id. Each value is
    {"wait_minutes": int | None, "raw_wait": str | None, "predicted": bool}; a predicted
    range has wait_minutes None and its display text in raw_wait.

    1. Try the Redis hash workers/scraper.py writes every ~15 min. Each entry is parsed
       independently so one malformed value doesn't discard the others.
    2. On Redis error or an empty hash, fall back to the database (see _fallback_rows) and
       best-effort populate Redis for the next read.
    3. If both fail, degrade to an empty map rather than raising — missing wait data always
       passes filters.

    Each outcome increments WAIT_TIMES_CACHE_OUTCOME (redis_hit / supabase_fallback /
    total_failure); the label keeps its Sprint 17 name for dashboard continuity.
    """
    try:
        raw = redis_client.hgetall(REDIS_HASH_KEY)
    except Exception:
        logger.warning("redis_unavailable_falling_back_to_database")
        raw = None

    if raw:
        wait_map: dict[str, dict] = {}
        for fid, v in raw.items():
            try:
                wait_map[fid] = _wait_info(json.loads(v))
            except (ValueError, AttributeError, TypeError):
                logger.warning("wait_times_entry_malformed", extra={"facility_id": fid})
        if wait_map:
            WAIT_TIMES_CACHE_OUTCOME.labels(outcome="redis_hit").inc()
        return wait_map

    try:
        rows = _fallback_rows()
    except Exception:
        logger.warning("wait_times_fallback_failed_returning_empty")
        WAIT_TIMES_CACHE_OUTCOME.labels(outcome="total_failure").inc()
        return {}

    wait_map = {r["facility_id"]: _wait_info(r) for r in rows}

    try:
        pipe = redis_client.pipeline()
        for r in rows:
            pipe.hset(REDIS_HASH_KEY, r["facility_id"], json.dumps({
                "wait_minutes": r["wait_minutes"],
                "raw_wait": r.get("raw_wait"),
                "predicted": bool(r.get("predicted", False)),
                "source": r.get("source"),
                "updated_at": r.get("recorded_at"),
            }, default=str))
        pipe.execute()
    except Exception:
        logger.warning("redis_populate_failed")

    WAIT_TIMES_CACHE_OUTCOME.labels(outcome="supabase_fallback").inc()
    return wait_map


def get_wait_minutes_map() -> dict[str, int | None]:
    """Minutes only, for the max-wait filter and existing callers."""
    return {fid: info["wait_minutes"] for fid, info in get_wait_map().items()}
```

- [ ] **Step 4: Add the demo branch to `backend/services/facilities.py`** — add imports `import demo_db` and `from config import demo_mode`. Replace `get_all_facilities` with:

```python
DEMO_FACILITIES_SQL = """
    select id::text as id, name, category, source_facility_type, accepted_severity,
           address, lat, lng, phone, business_status, weekday_hours
    from facilities
    where is_operational
      and (%(category)s::text is null or category = %(category)s)
      and (%(severity)s::text is null or %(severity)s = any(accepted_severity))
    order by name
"""


def _parse_weekday_hours(rows: list[dict]) -> list[dict]:
    """weekday_hours is a text column storing a JSON array string; parse it in place."""
    for f in rows:
        wh = f.get("weekday_hours")
        if isinstance(wh, str):
            try:
                f["weekday_hours"] = json_lib.loads(wh)
            except (ValueError, TypeError):
                f["weekday_hours"] = []
        elif wh is None:
            f["weekday_hours"] = []
    return rows


def _supabase_facilities(category: str | None, severity: str | None) -> list[dict]:
    params = {
        "select": "id:facility_id,name:facility_name,category,source_facility_type,"
                  "accepted_severity,address,lat,lng,phone,business_status,weekday_hours",
        "is_operational": "eq.true",
    }
    if category is not None:
        params["category"] = f"eq.{category}"
    if severity is not None:
        params["accepted_severity"] = f"cs.{{{severity}}}"
    return supabase_select("facilities_clean", params) or []


def get_all_facilities(
    category: str | None = None,
    severity: str | None = None,
) -> list[dict]:
    try:
        if demo_mode():
            rows = demo_db.fetch_all(DEMO_FACILITIES_SQL, {"category": category, "severity": severity})
        else:
            rows = _supabase_facilities(category, severity)
        return _parse_weekday_hours(rows)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("facilities_query_failed", extra={"error_type": type(e).__name__})
        raise HTTPException(status_code=503, detail="Database unavailable")
```

and append:

```python
def annotate_wait_details(records: list[dict], id_key: str, wait_map: dict[str, dict]) -> list[dict]:
    """Adds raw_wait (display text) and predicted to each record; never mutates the input."""
    annotated = []
    for r in records:
        info = wait_map.get(r[id_key], {})
        annotated.append({**r, "raw_wait": info.get("raw_wait"), "predicted": bool(info.get("predicted", False))})
    return annotated
```

- [ ] **Step 5: Use the details in `GET /facilities`** — in `backend/main.py`:

Change the two imports to:

```python
from services.facilities import get_all_facilities, apply_wait_filter, annotate_wait_details
from services.wait_times import get_wait_map, get_wait_minutes_map
```

In `facilities()`, replace

```python
    wait_map = await run_in_threadpool(get_wait_minutes_map)
    data = apply_wait_filter(data, "id", max_wait_minutes, wait_map)
```

with

```python
    wait_info = await run_in_threadpool(get_wait_map)
    wait_minutes = {fid: info["wait_minutes"] for fid, info in wait_info.items()}
    data = apply_wait_filter(data, "id", max_wait_minutes, wait_minutes)
    data = annotate_wait_details(data, "id", wait_info)
```

Leave `facilities_nearby()` as it is (it keeps `get_wait_minutes_map`).

- [ ] **Step 6: Update the route tests** — in `backend/tests/test_facilities_routes.py`, add below the imports:

```python
def _info(**minutes: int) -> dict:
    """{'a': 10} -> the get_wait_map() shape."""
    return {fid: {"wait_minutes": m, "raw_wait": None, "predicted": False} for fid, m in minutes.items()}
```

In `class TestFacilitiesRoute`, in every test that calls `main.facilities(...)` (not `facilities_nearby`), replace `patch("main.get_wait_minutes_map", return_value={...})` with `patch("main.get_wait_map", return_value=_info(...))` using the same ids and minutes — e.g. `{"a": 10, "b": 60}` becomes `_info(a=10, b=60)`, `{}` becomes `_info()`. Add one test to the class:

```python
    def test_facilities_carry_raw_wait_and_predicted(self):
        fake_data = [{"id": "a", "category": "hospital", "accepted_severity": ["urgent"]}]
        wait = {"a": {"wait_minutes": None, "raw_wait": "45m–2h", "predicted": True}}
        with patch("main.get_cached_facilities", return_value=(fake_data, None)), \
             patch("main.get_wait_map", return_value=wait):
            request = type("FakeRequest", (), {"headers": {}})()
            response = asyncio.run(main.facilities(request, max_wait_minutes=30))
        body = json.loads(response.body)
        assert body == [{"id": "a", "category": "hospital", "accepted_severity": ["urgent"],
                         "wait_minutes": None, "raw_wait": "45m–2h", "predicted": True}]
```

(add `import json` at the top of the file if it is not there).

- [ ] **Step 7: Add the demo branch to `backend/services/chat.py`** — replace the file's functions below `generate_session_title` with:

```python
def create_session(user_id: str, title: str) -> dict:
    if demo_mode():
        return guest_store.create_session(user_id, title)
    rows = supabase_insert("sessions", [{"user_id": user_id, "title": title}])
    return rows[0]


def add_message(session_id: str, user_id: str, role: str, content: str) -> dict:
    if demo_mode():
        return guest_store.add_message(session_id, user_id, role, content)
    rows = supabase_insert("messages", [{
        "session_id": session_id,
        "user_id": user_id,
        "role": role,
        "content": content,
    }])
    return rows[0]


def get_past_conversations(user_id: str, session_limit: int = 5, message_limit: int = 20) -> tuple[list, dict]:
    """
    Returns (sessions_list, messages_dict).
    sessions_list: up to `session_limit` most recent sessions for the user.
    messages_dict: { session_id: [last `message_limit` messages, chronological] }
    """
    if demo_mode():
        return guest_store.get_past_conversations(user_id, session_limit, message_limit)

    sessions = supabase_select("sessions", {
        "select": "*",
        "user_id": f"eq.{user_id}",
        "order": "updated_at.desc",
        "limit": str(session_limit),
    }) or []

    messages: dict[str, list] = {}
    for session in sessions:
        sid = session["id"]
        msgs = supabase_select("messages", {
            "select": "*",
            "session_id": f"eq.{sid}",
            "order": "created_at.desc",
            "limit": str(message_limit),
        }) or []
        messages[sid] = list(reversed(msgs))

    return sessions, messages


def get_older_messages(session_id: str, before_id: str, limit: int = 20, user_id: str | None = None) -> list:
    """
    Cursor-based pagination — returns messages older than `before_id`.
    Always hits the database; older messages are not cached.
    `user_id` scopes the read to the guest in demo mode.
    """
    if demo_mode():
        return guest_store.get_older_messages(user_id or "", session_id, before_id, limit)

    cursor = supabase_select("messages", {"select": "created_at", "id": f"eq.{before_id}"}, single=True)

    if not cursor:
        return []

    cursor_ts = cursor["created_at"]

    msgs = supabase_select("messages", {
        "select": "*",
        "session_id": f"eq.{session_id}",
        "created_at": f"lt.{cursor_ts}",
        "order": "created_at.desc",
        "limit": str(limit),
    }) or []

    return list(reversed(msgs))
```

and change the imports at the top to:

```python
from config import demo_mode
from db import supabase_select, supabase_insert
from services import guest_store
```

`guest_store.get_older_messages("", ...)` returns `[]` for an empty guest id, because `where guest_id = ''` would be a driver error: add this guard as the first line of `guest_store.get_older_messages`'s UUID check — change `if not (_is_uuid(session_id) and _is_uuid(before_id)):` to `if not (_is_uuid(guest_id) and _is_uuid(session_id) and _is_uuid(before_id)):`.

- [ ] **Step 8: Run the tests**

Run: `cd backend && doppler run -- python -m pytest tests/test_demo_services.py tests/test_facilities_routes.py tests/test_facilities.py tests/test_wait_times.py tests/test_chat_service.py tests/test_guest_store.py -q`
Expected: PASS. If `tests/test_wait_times.py` fails on the Redis-populate payload, the assertion at the `hset.call_args` lines compares the stored JSON: add `"predicted": False` to the expected dict there.

- [ ] **Step 9: Commit** (after approval)

```bash
git add backend/services/facilities.py backend/services/wait_times.py backend/services/chat.py backend/services/guest_store.py backend/main.py backend/tests/test_demo_services.py backend/tests/test_facilities_routes.py backend/tests/test_wait_times.py
git commit -m "feat: serve facilities, wait details and chat from demo postgres under demo mode"
```

---

### Task 7: Rate limit, busy response, guest chat routes

**Files:**
- Create: `backend/services/rate_limit.py`
- Modify: `backend/routers/chat.py`, `backend/tests/test_chat.py`
- Test: `backend/tests/test_rate_limit.py`

**Interfaces:**
- Consumes: `middleware.auth.get_actor`, `services.wait_times.redis_client`, `guest_store.record_event`, `guest_store.SessionNotFound`.
- Produces:
  - `rate_limit.check_rate_limit(guest_id: str, ip: str, now: float | None = None) -> int | None` — seconds to wait, or None when allowed.
  - `rate_limit.client_ip(request: Request) -> str`
  - `rate_limit.busy_response(retry_after: int) -> JSONResponse` — 429, body `{"code": "busy", "retry_after": n}`, header `Retry-After`.
  - `rate_limit.LLM_BUSY_RETRY_SECONDS = 60`

- [ ] **Step 1: Write the failing tests** — `backend/tests/test_rate_limit.py`:

```python
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import MagicMock, patch

import pytest

from services import rate_limit


class FakeRedis:
    """INCR/EXPIRE through a pipeline, enough for the limiter."""

    def __init__(self) -> None:
        self.counts: dict[str, int] = {}
        self.ttls: dict[str, int] = {}

    def pipeline(self) -> "FakeRedis":
        self._queued: list = []
        return self

    def incr(self, key: str) -> None:
        self._queued.append(("incr", key))

    def expire(self, key: str, seconds: int) -> None:
        self._queued.append(("expire", key, seconds))

    def execute(self) -> list:
        out: list = []
        for op in self._queued:
            if op[0] == "incr":
                self.counts[op[1]] = self.counts.get(op[1], 0) + 1
                out.append(self.counts[op[1]])
            else:
                self.ttls[op[1]] = op[2]
                out.append(True)
        return out


@pytest.fixture()
def fake_redis():
    fake = FakeRedis()
    with patch.object(rate_limit, "redis_client", fake):
        yield fake


def test_tenth_message_passes_eleventh_is_limited(fake_redis) -> None:
    for _ in range(10):
        assert rate_limit.check_rate_limit("g1", "1.1.1.1", now=1000.0) is None
    assert rate_limit.check_rate_limit("g1", "1.1.1.1", now=1000.0) == 200  # 600 - (1000 % 600)


def test_ip_limit_spans_guests(fake_redis) -> None:
    for i in range(30):
        assert rate_limit.check_rate_limit(f"g{i}", "9.9.9.9", now=0.0) is None
    assert rate_limit.check_rate_limit("fresh-guest", "9.9.9.9", now=0.0) == 600


def test_new_window_resets_the_count(fake_redis) -> None:
    for _ in range(11):
        rate_limit.check_rate_limit("g1", "1.1.1.1", now=10.0)
    assert rate_limit.check_rate_limit("g1", "1.1.1.1", now=610.0) is None


def test_raw_ip_never_reaches_redis_and_keys_expire(fake_redis) -> None:
    rate_limit.check_rate_limit("g1", "203.0.113.7", now=0.0)
    assert not any("203.0.113.7" in key for key in fake_redis.counts)
    assert set(fake_redis.ttls.values()) == {rate_limit.WINDOW_SECONDS}


def test_rate_limit_fails_open() -> None:
    broken = MagicMock()
    broken.pipeline.side_effect = ConnectionError("redis down")
    with patch.object(rate_limit, "redis_client", broken), \
         patch.object(rate_limit.sentry_sdk, "capture_message") as capture:
        assert rate_limit.check_rate_limit("g1", "1.1.1.1") is None
    capture.assert_called_once()


def _request(headers: dict[str, str], host: str | None = "10.0.0.1") -> MagicMock:
    request = MagicMock()
    request.headers = headers
    request.client = MagicMock(host=host) if host else None
    return request


def test_client_ip_prefers_x_real_ip_then_rightmost_forwarded() -> None:
    assert rate_limit.client_ip(_request({"x-real-ip": "5.5.5.5", "x-forwarded-for": "1.1.1.1"})) == "5.5.5.5"
    # the left-most entry is whatever the client typed; the proxy appends the real one
    assert rate_limit.client_ip(_request({"x-forwarded-for": "6.6.6.6, 7.7.7.7"})) == "7.7.7.7"
    assert rate_limit.client_ip(_request({})) == "10.0.0.1"
    assert rate_limit.client_ip(_request({}, host=None)) == "unknown"


def test_busy_response_shape() -> None:
    resp = rate_limit.busy_response(120)
    assert resp.status_code == 429 and resp.headers["retry-after"] == "120"
    assert json.loads(resp.body) == {"code": "busy", "retry_after": 120}
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd backend && doppler run -- python -m pytest tests/test_rate_limit.py -q`
Expected: FAIL with `ImportError: cannot import name 'rate_limit'`.

- [ ] **Step 3: Write `backend/services/rate_limit.py`**

```python
"""Fixed-window rate limit for the demo chat (the only route that spends LLM quota).

Per guest and per IP, in Redis. The IP is hashed before it becomes a key and the key lives one
window; it is never written to Postgres or to logs. If Redis is unreachable the limiter allows
the request: a broken limiter must not take the demo down.
"""
import hashlib
import logging
import time

import sentry_sdk
from fastapi.responses import JSONResponse
from starlette.requests import Request

from services.wait_times import redis_client

logger = logging.getLogger(__name__)

WINDOW_SECONDS = 600
GUEST_LIMIT = 10
IP_LIMIT = 30
LLM_BUSY_RETRY_SECONDS = 60


def client_ip(request: Request) -> str:
    real_ip = request.headers.get("x-real-ip", "").strip()
    if real_ip:
        return real_ip
    forwarded = [part.strip() for part in request.headers.get("x-forwarded-for", "").split(",") if part.strip()]
    if forwarded:
        return forwarded[-1]  # right-most: appended by our proxy, not typed by the client
    return request.client.host if request.client else "unknown"


def check_rate_limit(guest_id: str, ip: str, now: float | None = None) -> int | None:
    """Counts this request. Returns seconds until the window ends when over a limit, else None."""
    now = time.time() if now is None else now
    window = int(now // WINDOW_SECONDS)
    ip_hash = hashlib.sha256(ip.encode()).hexdigest()[:32]
    limits = [
        (f"rl:guest:{guest_id}:{window}", GUEST_LIMIT),
        (f"rl:ip:{ip_hash}:{window}", IP_LIMIT),
    ]
    try:
        pipe = redis_client.pipeline()
        for key, _ in limits:
            pipe.incr(key)
            pipe.expire(key, WINDOW_SECONDS)
        counts = pipe.execute()[0::2]
    except Exception as exc:
        logger.warning("rate_limit_unavailable", extra={"error_type": type(exc).__name__})
        sentry_sdk.capture_message("rate limiter unavailable, allowing requests", level="warning")
        return None

    if any(count > limit for count, (_, limit) in zip(counts, limits)):
        return WINDOW_SECONDS - int(now % WINDOW_SECONDS)
    return None


def busy_response(retry_after: int) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={"code": "busy", "retry_after": retry_after},
        headers={"Retry-After": str(retry_after)},
    )
```

- [ ] **Step 4: Run the limiter tests**

Run: `cd backend && doppler run -- python -m pytest tests/test_rate_limit.py -q` → PASS.

- [ ] **Step 5: Write the failing router tests** — in `backend/tests/test_chat.py`:

Change the import `from middleware.auth import get_current_user` to
`from middleware.auth import get_current_user, get_actor`, and in `_make_test_app` replace the override line with:

```python
        app.dependency_overrides[get_actor] = lambda: _FakeUser()
```

Add `is_guest = False` to `class _FakeUser`. Then append:

```python
# ── Guest demo behaviour ──────────────────────────────────────────────────────

class _FakeGuest:
    id = FAKE_USER_ID_STR
    email = None
    is_guest = True


def _guest_client() -> TestClient:
    app = FastAPI()
    app.dependency_overrides[get_actor] = lambda: _FakeGuest()
    app.include_router(chat_router)
    return TestClient(app)


_TRIAGE_RESULT = {
    "response": "Go to Toronto General.", "severity": "urgent", "reasoning": "r",
    "recommended_facility": {"id": "f1", "name": "TGH", "category": "hospital", "address": "a",
                             "lat": 43.6, "lng": -79.3, "distanceKm": 1.0},
    "nearby_facilities": [], "turn_type": "triage",
}


def _msg(role: str) -> dict:
    return {"id": f"m-{role}", "session_id": FAKE_SESSION_ID, "user_id": FAKE_USER_ID_STR,
            "role": role, "content": "x", "created_at": "2026-10-07T00:00:00Z"}


class TestGuestChat:
    def test_rate_limited_guest_gets_busy_and_nothing_is_stored(self):
        with patch("routers.chat.check_rate_limit", return_value=120), \
             patch("routers.chat.add_message") as add:
            resp = _guest_client().post("/chat/message", json={"session_id": FAKE_SESSION_ID, "content": "hi"})
        assert resp.status_code == 429 and resp.json() == {"code": "busy", "retry_after": 120}
        add.assert_not_called()

    def test_llm_quota_error_maps_to_busy(self):
        class Quota(Exception):
            status_code = 429

        agent = MagicMock()
        agent.respond.side_effect = Quota("rate limit")
        with patch("routers.chat.check_rate_limit", return_value=None), \
             patch("routers.chat.add_message", return_value=_msg("user")), \
             patch("services.llm_agent.LLMAgent", return_value=agent):
            resp = _guest_client().post("/chat/message", json={"session_id": FAKE_SESSION_ID, "content": "hi"})
        assert resp.status_code == 429 and resp.json() == {"code": "busy", "retry_after": 60}

    def test_guest_skips_profile_lookup_and_records_recommendation(self):
        agent = MagicMock()
        agent.respond.return_value = _TRIAGE_RESULT
        with patch("routers.chat.check_rate_limit", return_value=None), \
             patch("routers.chat.add_message", side_effect=[_msg("user"), _msg("assistant")]), \
             patch("services.llm_agent.LLMAgent", return_value=agent), \
             patch("db.supabase_select") as profile_lookup, \
             patch("routers.chat.guest_store.record_event") as record, \
             patch("routers.chat.should_sample", return_value=False):
            resp = _guest_client().post("/chat/message", json={"session_id": FAKE_SESSION_ID, "content": "hi"})
        assert resp.status_code == 200
        profile_lookup.assert_not_called()
        assert agent.respond.call_args.kwargs["user_profile"] is None
        record.assert_called_once_with(FAKE_USER_ID_STR, "recommendation_shown", FAKE_SESSION_ID)

    def test_foreign_session_is_404(self):
        from services.guest_store import SessionNotFound
        with patch("routers.chat.check_rate_limit", return_value=None), \
             patch("routers.chat.add_message", side_effect=SessionNotFound("s")):
            resp = _guest_client().post("/chat/message", json={"session_id": FAKE_SESSION_ID, "content": "hi"})
        assert resp.status_code == 404

    def test_new_guest_session_records_session_started(self):
        session = {"id": FAKE_SESSION_ID, "user_id": FAKE_USER_ID_STR, "title": "hi",
                   "created_at": "2026-10-07T00:00:00Z", "updated_at": "2026-10-07T00:00:00Z"}
        with patch("routers.chat.create_session", return_value=session), \
             patch("routers.chat.guest_store.record_event") as record:
            resp = _guest_client().post("/chat/sessions", json={"first_message": "hi"})
        assert resp.status_code == 200
        record.assert_called_once_with(FAKE_USER_ID_STR, "session_started", FAKE_SESSION_ID)

    def test_event_failure_does_not_fail_the_request(self):
        session = {"id": FAKE_SESSION_ID, "user_id": FAKE_USER_ID_STR, "title": "hi",
                   "created_at": "2026-10-07T00:00:00Z", "updated_at": "2026-10-07T00:00:00Z"}
        with patch("routers.chat.create_session", return_value=session), \
             patch("routers.chat.guest_store.record_event", side_effect=RuntimeError("db")):
            assert _guest_client().post("/chat/sessions", json={"first_message": "hi"}).status_code == 200

    def test_signed_in_user_is_not_rate_limited(self):
        agent = MagicMock()
        agent.respond.return_value = {**_TRIAGE_RESULT, "turn_type": "followup", "recommended_facility": None}
        with patch("routers.chat.check_rate_limit") as limit, \
             patch("routers.chat.add_message", side_effect=[_msg("user"), _msg("assistant")]), \
             patch("services.llm_agent.LLMAgent", return_value=agent), \
             patch("db.supabase_select", return_value=None):
            resp = TestClient(_make_test_app()).post(
                "/chat/message", json={"session_id": FAKE_SESSION_ID, "content": "hi"})
        assert resp.status_code == 200
        limit.assert_not_called()
```

- [ ] **Step 6: Run them to see them fail**

Run: `cd backend && doppler run -- python -m pytest tests/test_chat.py -q`
Expected: FAIL (`ImportError: cannot import name 'get_actor'` is gone after Task 5; failures now are `AttributeError: ... 'check_rate_limit'`).

- [ ] **Step 7: Change `backend/routers/chat.py`**

Imports — replace `from middleware.auth import get_current_user` with:

```python
from fastapi import HTTPException

from middleware.auth import get_actor
from services import guest_store
from services.rate_limit import LLM_BUSY_RETRY_SECONDS, busy_response, check_rate_limit, client_ip
```

In all five route signatures replace `Depends(get_current_user)` with `Depends(get_actor)`.

Add below `_trunc_uid`:

```python
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
```

In `create_new_session`, after `append_session_to_cache(user_id, session)` add:

```python
    await _record_guest_event(current_user, "session_started", str(session["id"]))
```

Change the message route decorator to `@router.post("/message", response_model=None)` and its return annotation to `-> Response | dict`. At the top of the body, right after `request_id = ...`:

```python
    if _is_guest(current_user):
        retry_after = await run_in_threadpool(check_rate_limit, user_id, client_ip(request))
        if retry_after is not None:
            return busy_response(retry_after)
```

Replace the line that stores the user message with:

```python
    try:
        user_msg = add_message(session_id=session_id, user_id=user_id, role="user", content=body.content)
    except guest_store.SessionNotFound:
        raise HTTPException(404, "Session not found") from None
```

Wrap the profile lookup so guests skip it — replace `user_profile: dict | None = None` and the `try/except` that follows it with:

```python
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
```

In the outer `except Exception as exc:` block of the agent call, add as its first lines:

```python
        if getattr(exc, "status_code", None) == 429:  # provider quota: Groq and Anthropic both expose status_code
            logger.warning("llm_quota_exhausted", extra={"request_id": request_id})
            return busy_response(LLM_BUSY_RETRY_SECONDS)
```

After the `triage = {...}` block is built, add:

```python
    if triage and triage["recommended_facility"]:
        await _record_guest_event(current_user, "recommendation_shown", session_id)
```

In `load_older_messages`, change the call to:

```python
    messages = get_older_messages(session_id=session_id, before_id=before_id, user_id=user_id)
```

- [ ] **Step 8: Run the tests**

Run: `cd backend && doppler run -- python -m pytest tests/test_chat.py tests/test_rate_limit.py tests/test_actor.py -q`
Expected: PASS. If an existing test asserts `get_older_messages` was called with exact keyword arguments, add `user_id=FAKE_USER_ID_STR` to that assertion.

- [ ] **Step 9: Commit** (after approval)

```bash
git add backend/services/rate_limit.py backend/routers/chat.py backend/tests/test_rate_limit.py backend/tests/test_chat.py
git commit -m "feat: rate limit guest chat and map quota errors to a busy response"
```

---

### Task 8: `/config`, `/feedback`, `/events` and the purge

**Files:**
- Create: `backend/routers/demo.py`
- Modify: `backend/services/retention.py`, `backend/main.py`
- Test: `backend/tests/test_demo_router.py`, `backend/tests/test_retention.py`

**Interfaces:**
- Consumes: `models.AppConfig / FeedbackRequest / GuestEventRequest`, `get_actor`, `guest_store.upsert_feedback / record_event / purge_expired_sessions`, `config.*`, `services.wait_times.redis_client`.
- Produces: `routers.demo.router`; `retention.purge_if_due() -> None`.

- [ ] **Step 1: Write the failing tests** — `backend/tests/test_retention.py`:

```python
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import MagicMock, patch

from services import retention


def test_purge_runs_when_lock_is_acquired() -> None:
    redis = MagicMock()
    redis.set.return_value = True
    with patch.object(retention, "redis_client", redis), \
         patch.object(retention.guest_store, "purge_expired_sessions", return_value=3) as purge:
        retention.purge_if_due()
    purge.assert_called_once_with()
    redis.set.assert_called_once_with("demo:purge:lock", "1", nx=True, ex=3600)


def test_purge_is_skipped_within_the_hour() -> None:
    redis = MagicMock()
    redis.set.return_value = None  # NX not acquired
    with patch.object(retention, "redis_client", redis), \
         patch.object(retention.guest_store, "purge_expired_sessions") as purge:
        retention.purge_if_due()
    purge.assert_not_called()


def test_purge_runs_when_redis_down() -> None:
    redis = MagicMock()
    redis.set.side_effect = ConnectionError("down")
    with patch.object(retention, "redis_client", redis), \
         patch.object(retention.guest_store, "purge_expired_sessions", return_value=0) as purge:
        retention.purge_if_due()
    purge.assert_called_once_with()


def test_purge_failure_is_swallowed() -> None:
    redis = MagicMock()
    redis.set.return_value = True
    with patch.object(retention, "redis_client", redis), \
         patch.object(retention.guest_store, "purge_expired_sessions", side_effect=RuntimeError("db")):
        retention.purge_if_due()  # must not raise
```

`backend/tests/test_demo_router.py`:

```python
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from middleware.auth import get_actor
from routers import demo

GUEST = "3f2b1c9e-8a47-4d1e-9c55-0a1b2c3d4e5f"
SID = "00000000-0000-0000-0000-0000000000a1"
MID = "00000000-0000-0000-0000-0000000000a2"


class _Guest:
    id = GUEST
    email = None
    is_guest = True


class _User:
    id = "u-1"
    email = "a@b.c"
    is_guest = False


def _client(actor: object = _Guest) -> TestClient:
    app = FastAPI()
    app.dependency_overrides[get_actor] = lambda: actor()
    app.include_router(demo.router)
    return TestClient(app)


def test_config_in_demo_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.delenv("DEMO_STARTER_PROMPTS", raising=False)
    body = _client().get("/config").json()
    assert body["demo_mode"] is True and body["modes_enabled"] == ["car"]
    assert body["downtown_fallback"] == {"lat": 43.6532, "lng": -79.3832}
    assert len(body["starter_prompts"]) == 3


def test_config_with_flag_off_enables_every_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DEMO_MODE", raising=False)
    body = _client().get("/config").json()
    assert body["demo_mode"] is False and body["modes_enabled"] == ["car", "bike", "bus", "walk"]


def test_config_needs_no_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEMO_MODE", "true")
    app = FastAPI()
    app.include_router(demo.router)  # no get_actor override: the route must not depend on it
    assert TestClient(app).get("/config").status_code == 200


def test_feedback_is_stored() -> None:
    with patch.object(demo.guest_store, "upsert_feedback", return_value=True) as upsert:
        resp = _client().post("/feedback", json={"session_id": SID, "message_id": MID,
                                                 "thumb": "down", "comment": "  wrong place  "})
    assert resp.status_code == 204 and resp.content == b""
    upsert.assert_called_once_with(GUEST, SID, MID, "down", "wrong place")


def test_blank_comment_is_stored_as_null() -> None:
    with patch.object(demo.guest_store, "upsert_feedback", return_value=True) as upsert:
        _client().post("/feedback", json={"session_id": SID, "message_id": MID, "thumb": "up", "comment": "   "})
    assert upsert.call_args.args[4] is None


def test_feedback_for_unknown_message_is_404() -> None:
    with patch.object(demo.guest_store, "upsert_feedback", return_value=False):
        resp = _client().post("/feedback", json={"session_id": SID, "message_id": MID, "thumb": "up"})
    assert resp.status_code == 404


def test_feedback_validates_the_body() -> None:
    assert _client().post("/feedback", json={"session_id": SID, "message_id": MID, "thumb": "meh"}).status_code == 422
    assert _client().post("/feedback", json={"session_id": "x", "message_id": MID, "thumb": "up"}).status_code == 422


def test_signed_in_users_cannot_post_guest_feedback_or_events() -> None:
    client = _client(_User)
    assert client.post("/feedback", json={"session_id": SID, "message_id": MID, "thumb": "up"}).status_code == 404
    assert client.post("/events", json={"type": "route_drawn", "session_id": SID}).status_code == 404


def test_route_drawn_event_is_recorded() -> None:
    with patch.object(demo.guest_store, "record_event", return_value=True) as record:
        resp = _client().post("/events", json={"type": "route_drawn", "session_id": SID})
    assert resp.status_code == 204
    record.assert_called_once_with(GUEST, "route_drawn", SID)


def test_event_for_foreign_session_is_404() -> None:
    with patch.object(demo.guest_store, "record_event", return_value=False):
        assert _client().post("/events", json={"type": "route_drawn", "session_id": SID}).status_code == 404


def test_clients_cannot_post_server_side_events() -> None:
    resp = _client().post("/events", json={"type": "recommendation_shown", "session_id": SID})
    assert resp.status_code == 422
```

- [ ] **Step 2: Run them to see them fail**

Run: `cd backend && doppler run -- python -m pytest tests/test_retention.py tests/test_demo_router.py -q`
Expected: FAIL (`ImportError: cannot import name 'demo'`, and `retention` has no `redis_client`).

- [ ] **Step 3: Write `backend/services/retention.py`** (replaces the stub)

```python
"""Chat-text retention: triggered when a new guest arrives, at most once per hour."""
import logging

from services import guest_store
from services.wait_times import redis_client

logger = logging.getLogger(__name__)

PURGE_LOCK_KEY = "demo:purge:lock"
PURGE_INTERVAL_SECONDS = 3600


def _purge_is_due() -> bool:
    try:
        return bool(redis_client.set(PURGE_LOCK_KEY, "1", nx=True, ex=PURGE_INTERVAL_SECONDS))
    except Exception:
        return True  # no Redis, no throttle: the delete is idempotent and indexed


def purge_if_due() -> None:
    if not _purge_is_due():
        return
    try:
        deleted = guest_store.purge_expired_sessions()
        logger.info("guest_sessions_purged", extra={"deleted": deleted})
    except Exception as exc:
        logger.warning("guest_purge_failed", extra={"error_type": type(exc).__name__})
```

- [ ] **Step 4: Write `backend/routers/demo.py`**

```python
"""Guest demo endpoints: public /config, and guest-only /feedback and /events."""
from fastapi import APIRouter, Depends, HTTPException, Response
from starlette.concurrency import run_in_threadpool

from config import ALL_MODES, DEMO_MODES, DOWNTOWN_TORONTO, demo_mode, starter_prompts
from middleware.auth import get_actor
from models import AppConfig, FeedbackRequest, GuestEventRequest
from services import guest_store

router = APIRouter(tags=["demo"])


def _guest_id(actor: object) -> str:
    if not getattr(actor, "is_guest", False):
        raise HTTPException(404, "Not available")
    return str(actor.id)  # type: ignore[attr-defined]


@router.get("/config")
def get_config() -> AppConfig:
    on = demo_mode()
    return AppConfig(
        demo_mode=on,
        starter_prompts=starter_prompts(),
        downtown_fallback=DOWNTOWN_TORONTO,
        modes_enabled=DEMO_MODES if on else ALL_MODES,
    )


@router.post("/feedback", status_code=204)
async def post_feedback(body: FeedbackRequest, actor: object = Depends(get_actor)) -> Response:
    guest_id = _guest_id(actor)
    comment = (body.comment or "").strip() or None
    stored = await run_in_threadpool(
        guest_store.upsert_feedback, guest_id, str(body.session_id), str(body.message_id), body.thumb, comment
    )
    if not stored:
        raise HTTPException(404, "Message not found")
    return Response(status_code=204)


@router.post("/events", status_code=204)
async def post_event(body: GuestEventRequest, actor: object = Depends(get_actor)) -> Response:
    guest_id = _guest_id(actor)
    recorded = await run_in_threadpool(guest_store.record_event, guest_id, body.type, str(body.session_id))
    if not recorded:
        raise HTTPException(404, "Session not found")
    return Response(status_code=204)
```

- [ ] **Step 5: Register the router** — in `backend/main.py` add `from routers.demo import router as demo_router` and, next to the other `include_router` lines, `app.include_router(demo_router)`.

- [ ] **Step 6: Run the whole backend suite**

Run: `cd backend && doppler run -- python -m pytest -q`
Expected: all pass; the only skips are tests marked `integration` and, if the container is stopped, the local-DB tests.

- [ ] **Step 7: Manual check against the local database**

Run (two terminals): 
`cd backend && DEMO_MODE=true POSTGRES_DB_URL_APP=postgresql://postgres:postgres@localhost:5433/medicoord_demo doppler run --preserve-env -- uvicorn main:app --port 8000`
then
`curl -s localhost:8000/config` → `"demo_mode":true`
`curl -s -o /dev/null -w "%{http_code}\n" localhost:8000/chat/sessions` → `400`
`curl -s -H "X-Guest-Id: 3f2b1c9e-8a47-4d1e-9c55-0a1b2c3d4e5f" localhost:8000/chat/sessions` → `{"sessions": [], "messages": {}}`
`curl -s localhost:8000/health` → contains `"demoDb":"ok"`.

- [ ] **Step 8: Commit** (after approval)

```bash
git add backend/routers/demo.py backend/services/retention.py backend/main.py backend/tests/test_demo_router.py backend/tests/test_retention.py
git commit -m "feat: add config, feedback and events endpoints with 30-day session purge"
```

---

# Milestone 2 — Frontend

All commands in this milestone run from `webapp/`. Type-check with `npx tsc -b` (not `tsc --noEmit`, which gives false negatives in this repo).

### Task 9: Config, guest id, API client, guest branch in `AuthProvider`

**Files:**
- Create: `webapp/src/lib/config.ts`, `webapp/src/lib/guest.ts`, `webapp/src/hooks/useConfig.ts`
- Modify: `webapp/src/lib/apiClient.ts`, `webapp/src/auth/AuthContext.tsx`
- Test: `webapp/src/lib/config.test.ts`, `webapp/src/lib/guest.test.ts`

**Interfaces:**
- Produces:
  - `getConfig(): Promise<AppConfig>` (one request per page load), `DEFAULT_CONFIG: AppConfig`, `resetConfigForTests(): void`.
  - `useConfig(): AppConfig` — `DEFAULT_CONFIG` until the request resolves.
  - `getGuestId(): string`, `captureInternalToken(search: string): void`, `getInternalToken(): string | null`.
  - `AuthContextValue.isGuest: boolean`.

- [ ] **Step 1: Write the failing tests** — `webapp/src/lib/guest.test.ts`:

```ts
// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { captureInternalToken, getGuestId, getInternalToken } from "./guest"

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/

describe("getGuestId", () => {
  beforeEach(() => localStorage.clear())
  afterEach(() => vi.restoreAllMocks())

  it("creates a uuid once and returns the same one afterwards", () => {
    const first = getGuestId()
    expect(first).toMatch(UUID)
    expect(getGuestId()).toBe(first)
    expect(localStorage.getItem("mc_guest_id")).toBe(first)
  })

  it("returns a fresh id when storage holds garbage", () => {
    localStorage.setItem("mc_guest_id", "<script>")
    const id = getGuestId()
    expect(id).toMatch(UUID)
    expect(localStorage.getItem("mc_guest_id")).toBe(id)
  })

  it("falls back to memory when storage throws", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("blocked") })
    const first = getGuestId()
    expect(first).toMatch(UUID)
    expect(getGuestId()).toBe(first)
  })
})

describe("internal token", () => {
  beforeEach(() => localStorage.clear())

  it("is captured from ?internal= and kept", () => {
    captureInternalToken("?internal=s3cret&x=1")
    expect(getInternalToken()).toBe("s3cret")
    captureInternalToken("")
    expect(getInternalToken()).toBe("s3cret")
  })

  it("is null when never set", () => {
    expect(getInternalToken()).toBeNull()
  })
})
```

`webapp/src/lib/config.test.ts`:

```ts
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { DEFAULT_CONFIG, getConfig, resetConfigForTests } from "./config"

const DEMO = {
  demo_mode: true,
  starter_prompts: ["a"],
  downtown_fallback: { lat: 43.6532, lng: -79.3832 },
  modes_enabled: ["car"],
}

describe("getConfig", () => {
  beforeEach(() => resetConfigForTests())
  afterEach(() => vi.unstubAllGlobals())

  it("fetches /config once and shares the result", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => DEMO })
    vi.stubGlobal("fetch", fetchMock)
    expect(await getConfig()).toEqual(DEMO)
    expect(await getConfig()).toEqual(DEMO)
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(String(fetchMock.mock.calls[0][0])).toMatch(/\/config$/)
  })

  it("falls back to non-demo defaults when the request fails", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")))
    expect(await getConfig()).toEqual(DEFAULT_CONFIG)
    expect(DEFAULT_CONFIG.demo_mode).toBe(false)
  })

  it("falls back when the server answers with an error", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, json: async () => ({}) }))
    expect(await getConfig()).toEqual(DEFAULT_CONFIG)
  })
})
```

- [ ] **Step 2: Run them to see them fail**

Run: `npm run test -- src/lib/guest.test.ts src/lib/config.test.ts`
Expected: FAIL — `Failed to resolve import "./guest"`.

- [ ] **Step 3: Write `webapp/src/lib/guest.ts`**

```ts
const GUEST_KEY = "mc_guest_id"
const INTERNAL_KEY = "mc_internal"
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i

// Used only when localStorage is blocked (private mode, strict settings): the id then lasts for the page.
let memoryGuestId: string | null = null

export function getGuestId(): string {
  try {
    const stored = localStorage.getItem(GUEST_KEY)
    if (stored && UUID_RE.test(stored)) return stored
    const fresh = crypto.randomUUID()
    localStorage.setItem(GUEST_KEY, fresh)
    return fresh
  } catch {
    memoryGuestId ??= crypto.randomUUID()
    return memoryGuestId
  }
}

/** `?internal=<token>` marks this browser as an internal tester from then on. */
export function captureInternalToken(search: string): void {
  const token = new URLSearchParams(search).get("internal")
  if (!token) return
  try {
    localStorage.setItem(INTERNAL_KEY, token)
  } catch {
    // storage blocked: this browser simply is not marked
  }
}

export function getInternalToken(): string | null {
  try {
    return localStorage.getItem(INTERNAL_KEY)
  } catch {
    return null
  }
}
```

- [ ] **Step 4: Write `webapp/src/lib/config.ts`**

```ts
import type { AppConfig } from "@shared/types"

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000"

/** What the app does when /config cannot be reached: today's non-demo behaviour. */
export const DEFAULT_CONFIG: AppConfig = {
  demo_mode: false,
  starter_prompts: [],
  downtown_fallback: { lat: 43.6532, lng: -79.3832 },
  modes_enabled: ["car", "bike", "bus", "walk"],
}

let pending: Promise<AppConfig> | null = null

export function getConfig(): Promise<AppConfig> {
  pending ??= fetch(`${BASE_URL}/config`)
    .then(res => (res.ok ? (res.json() as Promise<AppConfig>) : DEFAULT_CONFIG))
    .catch(() => DEFAULT_CONFIG)
  return pending
}

export function resetConfigForTests(): void {
  pending = null
}
```

- [ ] **Step 5: Write `webapp/src/hooks/useConfig.ts`**

```ts
import { useEffect, useState } from "react"
import type { AppConfig } from "@shared/types"
import { DEFAULT_CONFIG, getConfig } from "../lib/config"

export function useConfig(): AppConfig {
  const [config, setConfig] = useState<AppConfig>(DEFAULT_CONFIG)

  useEffect(() => {
    let cancelled = false
    void getConfig().then(loaded => { if (!cancelled) setConfig(loaded) })
    return () => { cancelled = true }
  }, [])

  return config
}
```

- [ ] **Step 6: Send the guest header in `webapp/src/lib/apiClient.ts`** — add imports:

```ts
import { getConfig } from "./config"
import { getGuestId, getInternalToken } from "./guest"
```

and replace the first statement of `apiFetch` (`const token = await authService.getAccessToken()`) and the `if (token) {...}` block with:

```ts
  const config = await getConfig()

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options.headers as Record<string, string> ?? {}),
  }

  if (config.demo_mode) {
    headers["X-Guest-Id"] = getGuestId()
    const internalToken = getInternalToken()
    if (internalToken) headers["X-Internal"] = internalToken
  } else {
    const token = await authService.getAccessToken()
    if (token) headers["Authorization"] = `Bearer ${token}`
  }
```

(delete the original `const headers = {...}` declaration that this replaces; keep everything from `const activeSpan` down).

- [ ] **Step 7: Add the guest branch to `webapp/src/auth/AuthContext.tsx`** — add imports:

```ts
import { getConfig } from "../lib/config"
import { captureInternalToken, getGuestId } from "../lib/guest"
```

Add `isGuest: boolean` to `AuthContextValue` (after `loading`). Add state `const [isGuest, setIsGuest] = useState(false)`. Replace the whole `useEffect` with:

```tsx
  useEffect(() => {
    let cancelled = false
    let unsubscribe = () => {}

    void getConfig().then(config => {
      if (cancelled) return

      if (config.demo_mode) {
        // Guest demo: the browser's random id stands in for the signed-in user everywhere.
        captureInternalToken(window.location.search)
        setUser({ id: getGuestId(), email: undefined })
        setIsGuest(true)
        setLoading(false)
        return
      }

      supabase.auth.getSession().then(({ data }) => {
        if (cancelled) return
        const session = data.session
        setUser(session?.user ? { id: session.user.id, email: session.user.email } : null)
        setLoading(false)
      })

      const { data: { subscription } } = supabase.auth.onAuthStateChange((_event, session) => {
        setUser(session?.user ? { id: session.user.id, email: session.user.email } : null)
      })
      unsubscribe = () => subscription.unsubscribe()
    })

    return () => {
      cancelled = true
      unsubscribe()
    }
  }, [])
```

In `signOut`, make it a no-op for guests — first line of the function: `if (isGuest) return`. Add `isGuest` to the provider's `value` object.

- [ ] **Step 8: Run the tests and the type check**

Run: `npm run test -- src/lib/guest.test.ts src/lib/config.test.ts` → PASS.
Run: `npx tsc -b` → no errors.

- [ ] **Step 9: Commit** (after approval)

```bash
git add webapp/src/lib/config.ts webapp/src/lib/guest.ts webapp/src/lib/config.test.ts webapp/src/lib/guest.test.ts webapp/src/hooks/useConfig.ts webapp/src/lib/apiClient.ts webapp/src/auth/AuthContext.tsx
git commit -m "feat: bootstrap guest identity from /config in the web app"
```

---

### Task 10: Hide sign-in, onboarding and prompts for guests

**Files:**
- Modify: `webapp/src/App.tsx`, `webapp/src/hooks/useProfile.ts`, `webapp/src/Menucomponents/Home.tsx`, `webapp/src/components/mobile/DrawerMenu.tsx`, `webapp/src/components/legal/LegalPageLayout.tsx`, `webapp/src/pages/LandingPage.tsx`

**Interfaces:**
- Consumes: `useAuth().isGuest`, `useAuth().loading`.

No unit test: these are conditional renders with no logic of their own; the Playwright smoke test (Task 16) asserts that no "Sign in" control is visible.

- [ ] **Step 1: `App.tsx`** — replace `ProtectedRoute` with:

```tsx
function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { user, isGuest } = useAuth()
  // Guests have no account pages: send them to the app instead of the landing page.
  if (isGuest) return <Navigate to="/app" replace />
  // ponytail: no loading guard — redirect on null, tolerate auth flash in phase 1
  if (!user) return <Navigate to="/" replace />
  return <>{children}</>
}
```

In `AppInner`: change `const { user } = useAuth()` to `const { user, isGuest } = useAuth()`; change the hook call to `useNotificationPermission(isGuest ? null : user?.id ?? null)`; and prefix three flags with the guest check:

```tsx
  const showOnboarding = Boolean(!isGuest && user && profile && !profile.getting_started_done)
```

```tsx
  const showInstallModal =
    !isGuest &&
    !installModalDismissed &&
```

```tsx
  const showPermissionPrompt =
    !isGuest &&
    !showInstallModal &&
```

- [ ] **Step 2: `hooks/useProfile.ts`** — change `const { user } = useAuth()` to `const { user, isGuest } = useAuth()`, and in `refetch` change the guard to `if (!user || isGuest) { setProfile(null); return }`. In `updateProfile` change the guard to `if (!user || isGuest) return`. Change the effect's dependency array to `[user, isGuest]`.

- [ ] **Step 3: `Menucomponents/Home.tsx`** — change `const { user } = useAuth()` to `const { user, isGuest } = useAuth()` and replace the `rightContent={user ? (` opening with:

```tsx
        rightContent={isGuest ? null : user ? (
```

(the rest of the ternary is unchanged).

- [ ] **Step 4: `components/mobile/DrawerMenu.tsx`** — change `const { user, signOut } = useAuth()` to `const { user, signOut, isGuest } = useAuth()`. Wrap the two blocks that start with the comments `{/* My profile */}` and `{/* Sign out */}` (each is one `<button>…</button>` element following its comment) in `{!isGuest && ( … )}`. Change the display name so a guest is not shown as `?`:

```tsx
  const initials = isGuest ? 'G' : email ? email[0].toUpperCase() : '?'
  const displayName = isGuest ? 'Guest' : email ? formatDisplayName(email) : ''
```

- [ ] **Step 5: `components/legal/LegalPageLayout.tsx`** — add `import { useAuth } from '../../auth/useAuth'`, add `const { isGuest, loading } = useAuth()` at the top of the component, and replace the opening tag of the header's right-hand container

```tsx
          <div className="flex items-center gap-3 min-[360px]:gap-6">
```

with

```tsx
          <div className="flex items-center gap-3 min-[360px]:gap-6" style={{ visibility: isGuest || loading ? 'hidden' : 'visible' }}>
```

- [ ] **Step 6: `pages/LandingPage.tsx`** — change `const { user } = useAuth()` to `const { user, loading } = useAuth()`. A guest is a truthy `user`, so the header already shows "Go to App" and "Get started" already navigates to `/app`. Only the pre-config flash needs handling: wrap the `user ? (…) : (…)` ternary that renders "Go to App" / "Sign in" in `{!loading && ( … )}`.

- [ ] **Step 7: Verify**

Run: `npx tsc -b && npm run lint` → no errors.
Manual, with the backend from Task 8 Step 7 running (`DEMO_MODE=true`, local DB) and `doppler run -- npm run dev`: open `http://localhost:5173/app` → no "Sign in"/"Get started" in the nav bar, no onboarding overlay, no install or notification prompt, the chat input is enabled. Open `/profile` → redirected to `/app`. Stop the backend, restart it without `DEMO_MODE`, reload → the sign-in buttons are back.

- [ ] **Step 8: Commit** (after approval)

```bash
git add webapp/src/App.tsx webapp/src/hooks/useProfile.ts webapp/src/Menucomponents/Home.tsx webapp/src/components/mobile/DrawerMenu.tsx webapp/src/components/legal/LegalPageLayout.tsx webapp/src/pages/LandingPage.tsx
git commit -m "feat: hide sign-in, onboarding and push prompts for guests"
```

---

### Task 11: Downtown fallback and drive-only modes

**Files:**
- Create: `webapp/src/lib/demoLocation.ts`
- Modify: `webapp/src/Menucomponents/subcomponent/ChatPanel.tsx`, `webapp/src/components/mobile/MobileLayout.tsx`, `webapp/src/components/mobile/BottomSheet.tsx`, `webapp/src/components/GpsPermissionModal.tsx`, `webapp/src/App.tsx`, `webapp/src/components/map/MapPanel.tsx`, `webapp/src/components/mobile/TransitModeGrid.tsx`, `webapp/src/components/triage/TriageCard.tsx`
- Test: `webapp/src/lib/demoLocation.test.ts`

**Interfaces:**
- Consumes: `useConfig()`, `AppConfig`.
- Produces: `resolveDemoCoords(coords: LatLng | null, config: AppConfig): { coords: LatLng | null; usedFallback: boolean }`, `isInToronto(coords: LatLng): boolean`, `FALLBACK_NOTICE: string`.

- [ ] **Step 1: Write the failing test** — `webapp/src/lib/demoLocation.test.ts`:

```ts
import { describe, expect, it } from "vitest"
import type { AppConfig } from "@shared/types"
import { isInToronto, resolveDemoCoords } from "./demoLocation"

const DOWNTOWN = { lat: 43.6532, lng: -79.3832 }
const demo: AppConfig = { demo_mode: true, starter_prompts: [], downtown_fallback: DOWNTOWN, modes_enabled: ["car"] }
const normal: AppConfig = { ...demo, demo_mode: false }

describe("isInToronto", () => {
  it("accepts points inside the box and rejects points outside", () => {
    expect(isInToronto({ lat: 43.70, lng: -79.40 })).toBe(true)
    expect(isInToronto({ lat: 45.50, lng: -73.57 })).toBe(false)  // Montreal
    expect(isInToronto({ lat: 43.70, lng: 79.40 })).toBe(false)   // wrong sign
  })

  it("treats the box edges as inside", () => {
    expect(isInToronto({ lat: 43.58, lng: -79.64 })).toBe(true)
    expect(isInToronto({ lat: 43.86, lng: -79.12 })).toBe(true)
    expect(isInToronto({ lat: 43.8601, lng: -79.12 })).toBe(false)
  })
})

describe("resolveDemoCoords", () => {
  it("keeps a Toronto position", () => {
    const here = { lat: 43.70, lng: -79.40 }
    expect(resolveDemoCoords(here, demo)).toEqual({ coords: here, usedFallback: false })
  })

  it("uses downtown when there is no position", () => {
    expect(resolveDemoCoords(null, demo)).toEqual({ coords: DOWNTOWN, usedFallback: true })
  })

  it("uses downtown when the position is outside Toronto", () => {
    expect(resolveDemoCoords({ lat: 45.50, lng: -73.57 }, demo)).toEqual({ coords: DOWNTOWN, usedFallback: true })
  })

  it("never substitutes a location outside demo mode", () => {
    expect(resolveDemoCoords(null, normal)).toEqual({ coords: null, usedFallback: false })
    const away = { lat: 45.50, lng: -73.57 }
    expect(resolveDemoCoords(away, normal)).toEqual({ coords: away, usedFallback: false })
  })
})
```

- [ ] **Step 2: Run it to see it fail**

Run: `npm run test -- src/lib/demoLocation.test.ts` → FAIL (`Failed to resolve import "./demoLocation"`).

- [ ] **Step 3: Write `webapp/src/lib/demoLocation.ts`**

```ts
import type { AppConfig } from "@shared/types"

export interface LatLng {
  lat: number
  lng: number
}

// The demo's facilities are all in Toronto; a position outside this box gives a useless recommendation.
const TORONTO_BOX = { minLat: 43.58, maxLat: 43.86, minLng: -79.64, maxLng: -79.12 }

export const FALLBACK_NOTICE = "Using downtown Toronto as your location"

export function isInToronto({ lat, lng }: LatLng): boolean {
  return lat >= TORONTO_BOX.minLat && lat <= TORONTO_BOX.maxLat
    && lng >= TORONTO_BOX.minLng && lng <= TORONTO_BOX.maxLng
}

/** In demo mode, a missing or out-of-town position is replaced by downtown Toronto. */
export function resolveDemoCoords(
  coords: LatLng | null,
  config: AppConfig,
): { coords: LatLng | null; usedFallback: boolean } {
  if (!config.demo_mode) return { coords, usedFallback: false }
  if (coords && isInToronto(coords)) return { coords, usedFallback: false }
  return { coords: config.downtown_fallback, usedFallback: true }
}
```

Run: `npm run test -- src/lib/demoLocation.test.ts` → PASS.

- [ ] **Step 4: Use it in the desktop chat** — `Menucomponents/subcomponent/ChatPanel.tsx`: add imports

```ts
import { useConfig } from "../../hooks/useConfig"
import { FALLBACK_NOTICE, resolveDemoCoords } from "../../lib/demoLocation"
```

Inside the component add `const config = useConfig()` and `const [usingFallbackLocation, setUsingFallbackLocation] = useState(false)`. In `handleSend`, directly after the `if (!coords) { … }` block that asks for geolocation, add:

```ts
    const located = resolveDemoCoords(coords, config)
    coords = located.coords
    setUsingFallbackLocation(located.usedFallback)
```

At the bottom of the component, replace the opening of the location line `{geo.permission === "denied" ? (` with:

```tsx
        {usingFallbackLocation ? (
          <p className="text-[10px] font-semibold text-center mt-2" style={{ color: '#7AA0B0' }}>
            {FALLBACK_NOTICE}
          </p>
        ) : geo.permission === "denied" ? (
```

- [ ] **Step 5: Use it on mobile** — `components/mobile/MobileLayout.tsx`: add the same two imports (paths `../../hooks/useConfig`, `../../lib/demoLocation`), add `const config = useConfig()` and `const [usingFallbackLocation, setUsingFallbackLocation] = useState(false)`. In `handleSend`, after `if (!coords) coords = await geo.requestOnce()`:

```ts
    const located = resolveDemoCoords(coords, config)
    coords = located.coords
    setUsingFallbackLocation(located.usedFallback)
```

Add `config` to the `useCallback` dependency array of `handleSend`. Pass `locationNotice={usingFallbackLocation ? FALLBACK_NOTICE : null}` to `<BottomSheet … />`.

`components/mobile/BottomSheet.tsx`: add `locationNotice: string | null` to `BottomSheetProps` and to the destructured props, and replace the text inside the "Security badge" `<span>`:

```tsx
          {locationNotice ?? <>🔒 SECURE &amp; CONFIDENTIAL · LOCATION SYNCED</>}
```

- [ ] **Step 6: Relabel the location-blocked modal for guests** — `components/GpsPermissionModal.tsx`: change the props interface and signature to

```tsx
interface GpsPermissionModalProps {
  onDismiss: () => void
  dismissLabel?: string
}

export function GpsPermissionModal({ onDismiss, dismissLabel = "Got it" }: GpsPermissionModalProps) {
```

and replace the button's text `Got it` with `{dismissLabel}`. In `App.tsx` change the modal usage to:

```tsx
        <GpsPermissionModal
          onDismiss={() => setGpsModalDismissed(true)}
          dismissLabel={isGuest ? "Continue with downtown Toronto" : undefined}
        />
```

- [ ] **Step 7: Show only enabled modes on the map** — `components/map/MapPanel.tsx`: add `import { useConfig } from '../../hooks/useConfig'`, add `const config = useConfig()` in the component, and replace `{(['car', 'bike', 'bus'] as const).map(mode => {` with:

```tsx
          {(['car', 'bike', 'bus'] as const).filter(mode => config.modes_enabled.includes(mode)).map(mode => {
```

- [ ] **Step 8: Mobile transit grid** — `components/mobile/TransitModeGrid.tsx`: add imports

```ts
import type { RouteResult, TravelModeKey } from '@shared/types'
import { useConfig } from '../../hooks/useConfig'
```

(replacing the existing `RouteResult` import), add below `CELLS`:

```ts
const MODE_KEY: Record<TransitMode, TravelModeKey> = { drive: 'car', cycle: 'bike', walk: 'walk' }
```

In the component, first lines:

```tsx
  const config = useConfig()
  const cells = CELLS.filter(cell => config.modes_enabled.includes(MODE_KEY[cell.mode]))
```

Replace the wrapper `<div className="grid grid-cols-3 gap-2 mt-3">` with

```tsx
    <div className="grid gap-2 mt-3" style={{ gridTemplateColumns: `repeat(${cells.length}, minmax(0, 1fr))` }}>
```

and `{CELLS.map(` with `{cells.map(`.

- [ ] **Step 9: Triage card chips** — `components/triage/TriageCard.tsx`: add `import { useConfig } from "../../hooks/useConfig"` and `const config = useConfig()` at the top of the `TriageCard` component (above any early return). Under the comment `{/* Transit mode chips */}` there is a `<div className="grid grid-cols-3 gap-1.5 mb-3">` with three child `<div>` chips marked 🚗, 🚲, 🚶. Replace that wrapper's opening tag with

```tsx
            <div
              className="grid gap-1.5 mb-3"
              style={{ gridTemplateColumns: `repeat(${1 + Number(config.modes_enabled.includes("bike")) + Number(config.modes_enabled.includes("walk"))}, minmax(0, 1fr))` }}
            >
```

and wrap the 🚲 chip in `{config.modes_enabled.includes("bike") && ( … )}` and the 🚶 chip in `{config.modes_enabled.includes("walk") && ( … )}`.

- [ ] **Step 10: Verify**

Run: `npx tsc -b && npm run lint && npm run test` → all pass.
Manual (demo backend running): block location for `localhost:5173` in the browser, reload `/app` → the modal's button reads "Continue with downtown Toronto"; send "Chest pain and shortness of breath" → a recommendation and a route appear, the line under the input reads "Using downtown Toronto as your location". The map shows only "Drive"; the triage card shows only the 🚗 chip.

- [ ] **Step 11: Commit** (after approval)

```bash
git add webapp/src/lib/demoLocation.ts webapp/src/lib/demoLocation.test.ts webapp/src/Menucomponents/subcomponent/ChatPanel.tsx webapp/src/components/mobile/MobileLayout.tsx webapp/src/components/mobile/BottomSheet.tsx webapp/src/components/GpsPermissionModal.tsx webapp/src/App.tsx webapp/src/components/map/MapPanel.tsx webapp/src/components/mobile/TransitModeGrid.tsx webapp/src/components/triage/TriageCard.tsx
git commit -m "feat: fall back to downtown toronto and show only the drive mode in the demo"
```

---

### Task 12: Starter prompts, medical notice, busy state

**Files:**
- Create: `webapp/src/lib/busy.ts`, `webapp/src/components/MedicalNotice.tsx`
- Modify: `webapp/src/hooks/useConversations.ts`, `webapp/src/App.tsx`, `webapp/src/Menucomponents/Home.tsx`, `webapp/src/Menucomponents/subcomponent/ChatPanel.tsx`, `webapp/src/components/mobile/MobileLayout.tsx`, `webapp/src/components/mobile/BottomSheet.tsx`, `webapp/src/components/mobile/SuggestionChips.tsx`
- Test: `webapp/src/lib/busy.test.ts`

**Interfaces:**
- Produces: `busyMessage(busyUntil: number, now: number): string`; `useConversations().busyUntil: number | null`; `<MedicalNotice />`.
- `ChatPanel` gains prop `busyUntil: number | null`; `MobileLayout` gains prop `busyUntil: number | null`; `BottomSheet` gains props `busyText: string | null` and `starterPrompts: string[]`; `SuggestionChips` gains prop `chips: readonly string[]`.

- [ ] **Step 1: Write the failing test** — `webapp/src/lib/busy.test.ts`:

```ts
import { describe, expect, it } from "vitest"
import { busyMessage } from "./busy"

describe("busyMessage", () => {
  it("rounds the wait up to whole minutes", () => {
    expect(busyMessage(61_000, 0)).toBe("MediCoord is busy right now. Try again in about 2 minutes.")
  })

  it("uses the singular for one minute and never says zero", () => {
    expect(busyMessage(60_000, 0)).toBe("MediCoord is busy right now. Try again in about 1 minute.")
    expect(busyMessage(1_000, 0)).toBe("MediCoord is busy right now. Try again in about 1 minute.")
    expect(busyMessage(0, 5_000)).toBe("MediCoord is busy right now. Try again in about 1 minute.")
  })
})
```

Run: `npm run test -- src/lib/busy.test.ts` → FAIL (`Failed to resolve import "./busy"`).

- [ ] **Step 2: Write `webapp/src/lib/busy.ts`**

```ts
export function busyMessage(busyUntil: number, now: number): string {
  const minutes = Math.max(1, Math.ceil((busyUntil - now) / 60_000))
  return `MediCoord is busy right now. Try again in about ${minutes} minute${minutes === 1 ? "" : "s"}.`
}
```

Run: `npm run test -- src/lib/busy.test.ts` → PASS.

- [ ] **Step 3: Write `webapp/src/components/MedicalNotice.tsx`**

```tsx
export function MedicalNotice() {
  return (
    <p
      data-testid="medical-notice"
      className="text-[10px] font-semibold text-center mt-1.5"
      style={{ color: '#F59E0B' }}
    >
      Not medical advice. In an emergency call 911.
    </p>
  )
}
```

- [ ] **Step 4: Track the busy state in `hooks/useConversations.ts`** — add `BusyResponse` to the `@shared/types` import, add `busyUntil: number | null` to `UseConversationsResult`, add state and a timer ref:

```ts
  const [busyUntil, setBusyUntil] = useState<number | null>(null)
  const busyTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => () => { if (busyTimerRef.current) clearTimeout(busyTimerRef.current) }, [])
```

In `sendMessage`, replace `if (!res.ok) return null` with:

```ts
    if (res.status === 429) {
      const body = await res.json().catch(() => null) as BusyResponse | null
      const waitMs = Math.max(1, body?.retry_after ?? 60) * 1000
      setBusyUntil(Date.now() + waitMs)
      if (busyTimerRef.current) clearTimeout(busyTimerRef.current)
      busyTimerRef.current = setTimeout(() => setBusyUntil(null), waitMs)
      return null
    }
    if (!res.ok) return null
```

Return `busyUntil` from the hook.

- [ ] **Step 5: Pass it down** — `App.tsx`: destructure `busyUntil` from `useConversations()` and add `busyUntil,` to `sharedProps`. `Menucomponents/Home.tsx`: add `busyUntil: number | null` to `HomeProps`, destructure it, and pass `busyUntil={busyUntil}` to `<ChatPanel />`. `components/mobile/MobileLayout.tsx`: add `busyUntil: number | null` to `MobileLayoutProps` and destructure it.

- [ ] **Step 6: Desktop chat** — `Menucomponents/subcomponent/ChatPanel.tsx`:

Add imports `import { MedicalNotice } from "../../components/MedicalNotice"` and `import { busyMessage } from "../../lib/busy"`. Add `busyUntil: number | null` to `ChatPanelProps` and destructure it. Add `const isBusy = busyUntil !== null`.

Starter prompts — delete the `SUGGESTIONS` constant at the top of the file and add inside the component:

```ts
  const FALLBACK_STARTERS = [
    "I have a fever and sore throat",
    "Chest pain and shortness of breath",
    "Twisted my ankle — it's swollen",
  ]
  const starters = config.starter_prompts.length > 0 ? config.starter_prompts : FALLBACK_STARTERS
```

Let `handleSend` take the text directly so a starter sends in one tap — change its first lines from

```ts
  const handleSend = async () => {
    if (!content.trim() || !user) return
    const text = content.trim()
```

to

```ts
  const handleSend = async (starter?: string) => {
    const text = (starter ?? content).trim()
    if (!text || !user || isBusy) return
```

Change the send button's `onClick={handleSend}` to `onClick={() => handleSend()}` (it would otherwise receive the click event as `starter`). `handleKeyDown` already calls `handleSend()`.

Replace `{SUGGESTIONS.map(s => (` with `{starters.map(s => (` and that button's `onClick={() => { if (user) setContent(s) }}` with `onClick={() => { void handleSend(s) }}`; add `data-testid="starter-prompt"` to the same button.

Busy banner — directly above `<ToolCallProgress stage={progressStage} />`:

```tsx
      {busyUntil !== null && (
        <div
          role="status"
          data-testid="busy-banner"
          className="mx-4 mb-2 rounded-lg text-[12px] font-medium"
          style={{ padding: '8px 12px', color: '#E2F1F5', background: 'rgba(0,210,255,0.08)', border: '1px solid rgba(0,210,255,0.3)' }}
        >
          {busyMessage(busyUntil, Date.now())}
        </div>
      )}
```

Disable sending while busy: on the send button change `disabled={!user || !content.trim()}` to `disabled={!user || !content.trim() || isBusy}`.

Notice — directly after the closing `)}` of the location line edited in Task 11 Step 4 (the last element inside the input area), add `<MedicalNotice />`.

- [ ] **Step 7: Mobile chat** — `components/mobile/SuggestionChips.tsx`: delete the `CHIPS` constant, add `chips: readonly string[]` to `SuggestionChipsProps` and the destructured props, and replace `{CHIPS.map(chip => {` with `{chips.map(chip => {`; add `data-testid="starter-prompt"` to the chip `<button>`.

`components/mobile/BottomSheet.tsx`: add `busyText: string | null` and `starterPrompts: string[]` to `BottomSheetProps` and the destructured props; add `import { MedicalNotice } from '../MedicalNotice'`. Change the chips line to `<SuggestionChips chips={starterPrompts} onSelect={onChipSelect} disabled={inputDisabled} />`. Above the `{/* Omni input */}` block add:

```tsx
      {busyText && (
        <div role="status" data-testid="busy-banner" className="flex-none px-4 mb-2 text-[12px]" style={{ color: '#E2F1F5' }}>
          {busyText}
        </div>
      )}
```

and inside the "Security badge" `<div>`, after the `<span>`, add `<MedicalNotice />`.

`components/mobile/MobileLayout.tsx`: add `import { busyMessage } from '../../lib/busy'`. Give `handleSend` the same optional argument:

```ts
  const handleSend = useCallback(async (starter?: string) => {
    const text = (starter ?? omniValue).trim()
    if (!text || !user || busyUntil !== null) return
    setOmniValue('')
```

(replacing the first three lines of its body; add `busyUntil` to its dependency array). Define the chip fallback next to the other constants at the top of the file:

```ts
const FALLBACK_STARTERS = ['I have a fever', 'Chest pain', 'Sore throat', 'Dizziness']
```

and change the `<BottomSheet … />` props:

```tsx
                onSend={() => { void handleSend() }}
                inputDisabled={!user || busyUntil !== null}
                onChipSelect={v => { void handleSend(v) }}
                starterPrompts={config.starter_prompts.length > 0 ? config.starter_prompts : FALLBACK_STARTERS}
                busyText={busyUntil !== null ? busyMessage(busyUntil, Date.now()) : null}
```

- [ ] **Step 8: Verify**

Run: `npx tsc -b && npm run lint && npm run test` → all pass.
Manual (demo backend running): `/app` shows the three starter prompts; one tap sends it. The notice "Not medical advice. In an emergency call 911." is visible under the input on desktop and in the mobile sheet (narrow the window under the mobile breakpoint). Send 11 messages within ten minutes → the 11th shows the busy banner and the send button is disabled.

- [ ] **Step 9: Commit** (after approval)

```bash
git add webapp/src/lib/busy.ts webapp/src/lib/busy.test.ts webapp/src/components/MedicalNotice.tsx webapp/src/hooks/useConversations.ts webapp/src/App.tsx webapp/src/Menucomponents/Home.tsx webapp/src/Menucomponents/subcomponent/ChatPanel.tsx webapp/src/components/mobile/MobileLayout.tsx webapp/src/components/mobile/BottomSheet.tsx webapp/src/components/mobile/SuggestionChips.tsx
git commit -m "feat: add one-tap starter prompts, medical notice and busy state"
```

---

### Task 13: Feedback control and the `route_drawn` event

**Files:**
- Create: `webapp/src/lib/guestEvents.ts`, `webapp/src/components/triage/FeedbackControl.tsx`
- Modify: `webapp/src/hooks/useTriageState.ts`, `webapp/src/Menucomponents/subcomponent/ChatPanel.tsx`, `webapp/src/components/mobile/MobileLayout.tsx`, `webapp/src/components/mobile/FacilityCardPanel.tsx`

**Interfaces:**
- Consumes: `apiFetch`, `getConfig`, `useAuth().isGuest`, types `FeedbackRequest`, `GuestEventRequest`, `Thumb`.
- Produces: `postRouteDrawn(sessionId: string): Promise<void>`; `<FeedbackControl sessionId messageId />`; `applyTriageResult(result, userCoords, sessionId?: string | null)`; `FacilityCardPanel` gains prop `feedback: { sessionId: string; messageId: string } | null`.

The posting logic is two short `fetch` calls with no branching worth a unit test; the smoke test (Task 16) asserts both requests return 204.

- [ ] **Step 1: Write `webapp/src/lib/guestEvents.ts`**

```ts
import type { GuestEventRequest } from "@shared/types"
import { apiFetch } from "./apiClient"
import { getConfig } from "./config"

const sentForSession = new Set<string>()

/** Tells the backend a real road route was drawn. Sent at most once per session; never throws. */
export async function postRouteDrawn(sessionId: string): Promise<void> {
  const config = await getConfig()
  if (!config.demo_mode || sentForSession.has(sessionId)) return
  sentForSession.add(sessionId)
  const body: GuestEventRequest = { type: "route_drawn", session_id: sessionId }
  try {
    await apiFetch("/events", { method: "POST", body: JSON.stringify(body) })
  } catch {
    // the event is a measurement, not a feature: a failure must not disturb the user
  }
}
```

- [ ] **Step 2: Emit it from `hooks/useTriageState.ts`** — add `import { postRouteDrawn } from "../lib/guestEvents"`. Change the `applyTriageResult` signature to:

```ts
  const applyTriageResult = useCallback(async (
    result: TriageResult,
    userCoords: { lat: number; lng: number } | null,
    sessionId?: string | null,
  ) => {
```

and directly after the `roadGeometry = await fetchRoadGeometry(userCoords, bestFacility)` block (before the `setTriage(prev => …)` call) add:

```ts
        // Only real road geometry counts as "route drawn"; the straight-line fallback does not.
        if (roadGeometry && sessionId) void postRouteDrawn(sessionId)
```

- [ ] **Step 3: Write `webapp/src/components/triage/FeedbackControl.tsx`**

```tsx
import { useState } from "react"
import type { FeedbackRequest, Thumb } from "@shared/types"
import { apiFetch } from "../../lib/apiClient"

interface FeedbackControlProps {
  sessionId: string
  messageId: string
}

type SaveState = "idle" | "saving" | "saved" | "error"

const BUTTON_STYLE: React.CSSProperties = {
  padding: "4px 10px",
  borderRadius: 8,
  fontSize: 13,
  cursor: "pointer",
  background: "rgba(10, 29, 39, 0.6)",
  color: "#E2F1F5",
}

export function FeedbackControl({ sessionId, messageId }: FeedbackControlProps) {
  const [thumb, setThumb] = useState<Thumb | null>(null)
  const [comment, setComment] = useState("")
  const [state, setState] = useState<SaveState>("idle")

  const send = async (nextThumb: Thumb, nextComment: string) => {
    setThumb(nextThumb)
    setState("saving")
    const body: FeedbackRequest = {
      session_id: sessionId,
      message_id: messageId,
      thumb: nextThumb,
      comment: nextComment.trim() || null,
    }
    try {
      const res = await apiFetch("/feedback", { method: "POST", body: JSON.stringify(body) })
      setState(res.ok ? "saved" : "error")
    } catch {
      setState("error")
    }
  }

  const border = (value: Thumb) =>
    `1px solid ${thumb === value ? "rgba(72,246,193,0.7)" : "rgba(28,70,89,0.6)"}`

  return (
    <div data-testid="feedback-control" className="mt-2 flex flex-col gap-2" style={{ fontFamily: "var(--font-sans)" }}>
      <div className="flex items-center gap-2">
        <span className="text-[11px]" style={{ color: "#7AA0B0" }}>Was this helpful?</span>
        <button type="button" aria-label="Helpful" aria-pressed={thumb === "up"} data-testid="feedback-up"
          onClick={() => { void send("up", "") }} style={{ ...BUTTON_STYLE, border: border("up") }}>
          👍
        </button>
        <button type="button" aria-label="Not helpful" aria-pressed={thumb === "down"} data-testid="feedback-down"
          onClick={() => { void send("down", comment) }} style={{ ...BUTTON_STYLE, border: border("down") }}>
          👎
        </button>
        {state === "saved" && <span data-testid="feedback-saved" className="text-[11px]" style={{ color: "#48F6C1" }}>Thanks</span>}
        {state === "error" && <span className="text-[11px]" style={{ color: "#F59E0B" }}>Could not save. Try again.</span>}
      </div>

      {thumb === "down" && (
        <div className="flex gap-2">
          <input
            aria-label="What went wrong? (optional)"
            placeholder="What went wrong? (optional)"
            value={comment}
            maxLength={2000}
            onChange={e => setComment(e.target.value)}
            className="flex-1 text-[12px] rounded-lg px-2 py-1.5 focus:outline-none"
            style={{ background: "rgba(10,29,39,0.6)", border: "1px solid rgba(28,70,89,0.6)", color: "#E2F1F5" }}
          />
          <button type="button" disabled={state === "saving"} onClick={() => { void send("down", comment) }}
            style={{ ...BUTTON_STYLE, border: "1px solid rgba(28,70,89,0.6)" }}>
            Send
          </button>
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 4: Desktop** — `Menucomponents/subcomponent/ChatPanel.tsx`: add `import { FeedbackControl } from "../../components/triage/FeedbackControl"` and `import { useAuth } from "../../auth/useAuth"`, and `const { isGuest } = useAuth()` in the component. Change the `onTriageResult` prop type to

```ts
  onTriageResult: (result: TriageResult, coords: { lat: number; lng: number } | null, sessionId?: string | null) => Promise<void>
```

and the call in `handleSend` to `await onTriageResult(response.triage, coords, sid)`. Inside the block `{isLastAssistant && showTriageCard && ( <div className="mt-1 max-w-[80%]"> … </div> )}`, after `<TriageCard … />` add:

```tsx
                      {isGuest && activeSessionId && triage.recommendedFacility && (
                        <FeedbackControl sessionId={activeSessionId} messageId={msg.id} />
                      )}
```

- [ ] **Step 5: Mobile** — `components/mobile/MobileLayout.tsx`: change `handleApplyTriage` to take and forward the session id:

```ts
  const handleApplyTriage = useCallback(async (
    result: TriageResult,
    coords: { lat: number; lng: number } | null,
    sessionId: string,
  ) => {
    await applyTriageResult(result, coords, sessionId)
  }, [applyTriageResult])
```

call it with `await handleApplyTriage(response.triage, coords, sid)`, add `const { user, isGuest } = useAuth()` (replacing `const { user } = useAuth()`), and compute the feedback target above the `return`:

```ts
  const lastAssistant = [...messages].reverse().find(m => m.role === 'assistant')
  const feedback = isGuest && activeSessionId && lastAssistant
    ? { sessionId: activeSessionId, messageId: lastAssistant.id }
    : null
```

Pass `feedback={feedback}` to `<FacilityCardPanel … />`.

`components/mobile/FacilityCardPanel.tsx`: add `import { FeedbackControl } from '../triage/FeedbackControl'`, add `feedback: { sessionId: string; messageId: string } | null` to `FacilityCardPanelProps` and the destructured props, and directly after the "Get Directions →" `</button>` add:

```tsx
        {feedback && <FeedbackControl sessionId={feedback.sessionId} messageId={feedback.messageId} />}
```

- [ ] **Step 6: Verify**

Run: `npx tsc -b && npm run lint && npm run test` → all pass.
Manual (demo backend + local DB): send a starter prompt until a recommendation appears. In the browser's network tab: `POST /events` → 204 once the route line is drawn; click 👎, type a comment, Send → `POST /feedback` → 204 and "Thanks" appears. Then:
`./backend/script.demo.local.sh --local query "select type, count(*) from events group by 1; select thumb, comment from feedback"` → three event types, one feedback row.

- [ ] **Step 7: Commit** (after approval)

```bash
git add webapp/src/lib/guestEvents.ts webapp/src/components/triage/FeedbackControl.tsx webapp/src/hooks/useTriageState.ts webapp/src/Menucomponents/subcomponent/ChatPanel.tsx webapp/src/components/mobile/MobileLayout.tsx webapp/src/components/mobile/FacilityCardPanel.tsx
git commit -m "feat: add recommendation feedback and the route-drawn event"
```

---

### Task 14: Wait-time label and the disclosure page

**Files:**
- Modify: `webapp/src/utils/waitTimeUtils.ts`, `webapp/src/utils/waitTimeUtils.test.ts`, `webapp/src/components/map/components/UnifiedFacilityPopup.tsx`, `webapp/src/components/map/components/FacilityMarkerLayer.tsx`, `webapp/src/pages/DataDisclosurePage.tsx`

**Interfaces:**
- Produces: `formatWaitLabel(waitMinutes: number | null | undefined, rawWait: string | null | undefined, predicted: boolean | undefined): string | null`.

- [ ] **Step 1: Write the failing test** — append to `webapp/src/utils/waitTimeUtils.test.ts` (add `formatWaitLabel` to the existing import from `./waitTimeUtils`):

```ts
describe("formatWaitLabel", () => {
  it("shows live minutes", () => {
    expect(formatWaitLabel(42, "42 min", false)).toBe("42 min wait")
    expect(formatWaitLabel(0, null, false)).toBe("0 min wait")
  })

  it("shows a predicted range with its marker", () => {
    expect(formatWaitLabel(null, "45m–2h", true)).toBe("45m–2h (predicted)")
  })

  it("shows nothing when there is no data", () => {
    expect(formatWaitLabel(null, null, false)).toBeNull()
    expect(formatWaitLabel(undefined, undefined, undefined)).toBeNull()
  })

  it("shows nothing for a predicted row without text", () => {
    expect(formatWaitLabel(null, "  ", true)).toBeNull()
  })
})
```

Run: `npm run test -- src/utils/waitTimeUtils.test.ts` → FAIL (`formatWaitLabel is not a function`).

- [ ] **Step 2: Implement** — append to `webapp/src/utils/waitTimeUtils.ts`:

```ts
/** Popup text for an ER wait: live minutes, a predicted range, or nothing. */
export function formatWaitLabel(
  waitMinutes: number | null | undefined,
  rawWait: string | null | undefined,
  predicted: boolean | undefined,
): string | null {
  if (predicted) {
    const range = rawWait?.trim()
    return range ? `${range} (predicted)` : null
  }
  return waitMinutes != null ? `${waitMinutes} min wait` : null
}
```

Run: `npm run test -- src/utils/waitTimeUtils.test.ts` → PASS.

- [ ] **Step 3: Show it in the popup** — `components/map/components/UnifiedFacilityPopup.tsx`: add `import { formatWaitLabel } from '../../../utils/waitTimeUtils'`; add to `UnifiedFacilityPopupProps`

```ts
  wait_minutes?:  number | null
  raw_wait?:      string | null
  predicted?:     boolean
```

add the three names to the destructured props, add `const waitLabel = formatWaitLabel(wait_minutes, raw_wait, predicted)` next to the other derived values, and directly before `{phone && (` add:

```tsx
        {waitLabel && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
            <i className="ti ti-clock" style={{ fontSize: 11, color: '#8C8273' }} />
            <span style={{ fontSize: 10, color: '#7A756D', fontWeight: 500 }}>{waitLabel}</span>
          </div>
        )}
```

`components/map/components/FacilityMarkerLayer.tsx`: in the second `<UnifiedFacilityPopup` (the one inside `displayedFacilities.map`, which already passes `phone` and `weekday_hours`) add:

```tsx
              wait_minutes={facility.wait_minutes}
              raw_wait={facility.raw_wait}
              predicted={facility.predicted}
```

- [ ] **Step 4: Rewrite the stored-data entries on the disclosure page** — `pages/DataDisclosurePage.tsx`: change `lastUpdated="June 24, 2026"` to `lastUpdated="October 7, 2026"`, and add these three objects at the start of the `disclosureItems` array (each uses the array's existing keys `data`, `badge`, `why`, `stored`, `shared`):

```ts
    {
      data: 'Guest demo: random browser ID',
      badge: 'No account',
      why: 'The public demo needs no sign-in. A random ID created in your browser keeps your conversations together and counts messages for the usage limit.',
      stored: 'In your browser (local storage) and in our demo database. It is not linked to your name, email or IP address. Clearing your browser data starts a new, empty guest.',
      shared: 'Never shared.'
    },
    {
      data: 'Guest demo: chat text',
      badge: 'Deleted after 30 days',
      why: 'Shown back to you when you return in the same browser, and reviewed by the team to improve recommendations.',
      stored: 'Demo database (Railway, PostgreSQL). Each conversation and its messages are deleted 30 days after the conversation started.',
      shared: 'Sent to the language-model provider (Groq) to generate replies. Not sold or shared otherwise.'
    },
    {
      data: 'Guest demo: feedback and usage events',
      badge: 'Kept',
      why: 'Your thumbs up/down and optional comment, and three counters (conversation started, recommendation shown, route drawn), tell us whether the demo works.',
      stored: 'Demo database, linked only to the random browser ID. No IP address is stored; it is used for ten minutes, in hashed form, to limit abuse.',
      shared: 'Never shared.'
    },
```

Deletion requests need a public contact address, and the site shows none today. **Ask the user which
address to publish** (do not reuse a personal address without asking). With the answer in hand, add
directly below the opening paragraph of the page (the `<p>` that ends with the Privacy Policy link),
substituting the address in both places:

```tsx
      <p className="text-sm md:text-body-md text-[#85A4B1] leading-relaxed mt-4">
        To have your guest demo data deleted, email <a href="mailto:CONTACT_ADDRESS">CONTACT_ADDRESS</a> with
        the browser ID shown in your browser's local storage under <code>mc_guest_id</code>.
      </p>
```

If the user prefers not to publish an address yet, skip this paragraph and record in the changelog
that the disclosure page has no deletion contact.

- [ ] **Step 5: Verify**

Run: `npx tsc -b && npm run lint && npm run test && npm run build` → all pass (the build also re-prerenders `/data-disclosure`).

- [ ] **Step 6: Commit** (after approval)

```bash
git add webapp/src/utils/waitTimeUtils.ts webapp/src/utils/waitTimeUtils.test.ts webapp/src/components/map/components/UnifiedFacilityPopup.tsx webapp/src/components/map/components/FacilityMarkerLayer.tsx webapp/src/pages/DataDisclosurePage.tsx
git commit -m "feat: show predicted wait ranges and disclose guest demo data"
```

---

### Task 15: `/app` 404 on production

**Files:** depends on the cause. Candidates: Vercel project settings (no file), `webapp/vercel.json`.

This task is a diagnosis. Follow superpowers:systematic-debugging: find the cause before changing anything.

- [ ] **Step 1: Reproduce and record the response**

Run:
```bash
for p in / /app /app/ /for-engineers /data-disclosure /does-not-exist; do
  printf "%-22s " "$p"; curl -s -o /dev/null -w "%{http_code} %{content_type}\n" "https://medicoord.nknext.dev$p"
done
curl -sI https://medicoord.nknext.dev/app | grep -i -E "^(HTTP|x-vercel|server|location)"
```
Record the status of each path. Expected pattern for hypothesis 1: prerendered paths 200, `/app` and `/does-not-exist` 404.

- [ ] **Step 2: Check hypothesis 1 — root directory**

Use the Vercel tools (`mcp__vercel__list_projects`, then `mcp__vercel__get_project`) and read `rootDirectory`, `outputDirectory`, `framework` and `buildCommand`. `webapp/vercel.json` holds the SPA rewrite (`/(.*) → /index.html`); it only applies when `rootDirectory` is `webapp`. If `rootDirectory` is empty or anything else, this is the cause.

- [ ] **Step 3: Check hypothesis 3 — stale production alias**

Use `mcp__vercel__list_deployments` for the project: compare the production deployment's commit with `git rev-parse origin/main`. If production points at an old deployment, request that deployment's `/app` by its own `*.vercel.app` URL and compare.

- [ ] **Step 4: Check hypothesis 2 — `cleanUrls` and the catch-all**

Only if 1 and 3 are ruled out: run `npm run build && npx vercel build` locally and inspect `.vercel/output/config.json` for the generated routes; check whether a `handle: filesystem` step precedes the rewrite and whether `/app` reaches it.

- [ ] **Step 5: Apply the fix that matches the cause**

- Cause 1: set the project's Root Directory to `webapp` in Vercel (ask the user to confirm; it is a project setting, done with `mcp__vercel__update_project` or in the dashboard), then redeploy.
- Cause 2: replace the contents of `webapp/vercel.json` with a rewrite that excludes real files:

```json
{
  "cleanUrls": true,
  "rewrites": [{ "source": "/((?!assets/|.*\\..*).*)", "destination": "/index.html" }]
}
```

- Cause 3: promote the current deployment (`mcp__vercel__request_promote`), with the user's confirmation.
- None of the three: stop and report the evidence from Steps 1–4 to the user.

- [ ] **Step 6: Verify on the preview deployment of this branch**

Run the loop from Step 1 against the preview URL. Expected: `/app` → `200 text/html`, `/does-not-exist` → `200 text/html` (the SPA redirects it to `/`), prerendered pages still `200`.

- [ ] **Step 7: Commit** (only if a file changed; after approval)

```bash
git add webapp/vercel.json
git commit -m "fix: serve the spa shell for /app on vercel"
```

---

# Milestone 3 — Hardening

### Task 16: Remove the hardcoded key file; deployed smoke test

**Files:**
- Delete: `webapp/src/Menucomponents/utils/geoapify.ts`
- Create: `webapp/playwright.smoke.config.ts`, `webapp/e2e/guest-demo.smoke.spec.ts`
- Modify: `webapp/package.json` (one script)

- [ ] **Step 1: Confirm the file has no importers, then delete it**

Run: `graphify query "who imports getRouteMatrix or mapMatrixToRoutes from utils/geoapify"` then
`cd webapp && grep -rn "utils/geoapify\|getRouteMatrix\|mapMatrixToRoutes" src | grep -v "utils/geoapify.ts"`
Expected: no output.

Run: `git rm webapp/src/Menucomponents/utils/geoapify.ts && cd webapp && npx tsc -b`
Expected: no type errors. If `GetRouteMatrixParams`, `RouteMatrixResponse` or `RouteData` in `src/Menucomponents/types.ts` are now unused, leave them (other hackathon files reference that module).

- [ ] **Step 2: Ask the user to rotate the key** — the key was committed in the file just deleted and stays in git history. The user revokes it in the Geoapify dashboard and puts the new one in Doppler (`GEOAPIFY_API_KEY` for the backend scripts, `VITE_GEOAPIFY_API_KEY` for the web build, marked Unmasked for the Vercel sync). Do not print either value. Record in the changelog that rotation was requested and whether it was done.

- [ ] **Step 3: Write `webapp/playwright.smoke.config.ts`**

```ts
import { defineConfig } from "@playwright/test"

// Runs against an already-deployed site (preview or production). No local servers are started.
//   SMOKE_BASE_URL=https://<preview>.vercel.app npm run test:smoke
const baseURL = process.env.SMOKE_BASE_URL
if (!baseURL) throw new Error("SMOKE_BASE_URL is not set")

export default defineConfig({
  testDir: "./e2e",
  testMatch: /.*\.smoke\.spec\.ts/,
  timeout: 120_000,
  retries: 1,
  use: {
    baseURL,
    trace: "retain-on-failure",
    viewport: { width: 1280, height: 800 },
    permissions: ["geolocation"],
    geolocation: { latitude: 43.6629, longitude: -79.3957 }, // University of Toronto, inside the demo area
  },
})
```

Add to `webapp/package.json` scripts, after `"test:e2e"`:

```json
    "test:smoke": "playwright test -c playwright.smoke.config.ts",
```

Check that the existing local config does not pick the smoke file up: in `webapp/playwright.config.ts` add `testIgnore: /.*\.smoke\.spec\.ts/,` below `testDir: "./e2e",`.

- [ ] **Step 4: Write `webapp/e2e/guest-demo.smoke.spec.ts`**

```ts
import { expect, test } from "@playwright/test"

// The one path the demo is measured on: land → starter → recommendation → route drawn → feedback.
// The LLM may ask a follow-up before recommending, so the test answers up to three times.
const FOLLOW_UP_ANSWER =
  "It started an hour ago, the pain is strong and constant, I am 45 with no other conditions. Please recommend where to go."

test("guest reaches a drawn route and leaves feedback", async ({ page }) => {
  const routeDrawn = page.waitForResponse(
    res => res.url().endsWith("/events") && res.request().method() === "POST",
    { timeout: 110_000 },
  )

  await page.goto("/")
  // "Go to App" only renders once /config has resolved and the guest exists; before that the
  // "Get started" button would open the sign-up modal instead of navigating.
  await expect(page.getByRole("button", { name: "Go to App" })).toBeVisible()
  await expect(page.getByRole("button", { name: "Sign in" })).toHaveCount(0)
  await page.getByRole("button", { name: "Get started" }).first().click()
  await expect(page).toHaveURL(/\/app$/)

  await expect(page.getByTestId("medical-notice")).toBeVisible()
  await expect(page.getByRole("button", { name: "Sign in" })).toHaveCount(0)

  await page.getByTestId("starter-prompt").nth(1).click() // "Chest pain and shortness of breath"

  const feedback = page.getByTestId("feedback-control")
  const input = page.getByPlaceholder("Describe how you feel…")
  for (let attempt = 0; attempt < 3; attempt++) {
    try {
      await feedback.waitFor({ state: "visible", timeout: 30_000 })
      break
    } catch {
      await expect(page.getByTestId("busy-banner")).toHaveCount(0)
      await input.fill(FOLLOW_UP_ANSWER)
      await input.press("Enter")
    }
  }
  await expect(feedback).toBeVisible()

  expect((await routeDrawn).status()).toBe(204)
  await expect(page.locator(".leaflet-overlay-pane path").first()).toBeVisible()

  const saved = page.waitForResponse(
    res => res.url().endsWith("/feedback") && res.request().method() === "POST",
  )
  await page.getByTestId("feedback-up").click()
  expect((await saved).status()).toBe(204)
  await expect(page.getByTestId("feedback-saved")).toBeVisible()
})
```

- [ ] **Step 5: Run it against the preview deployment** (needs the backend deployed with `DEMO_MODE=true` and Task 2's migration applied remotely; ask the user for the preview URL)

Run: `cd webapp && SMOKE_BASE_URL=https://<preview-url> npm run test:smoke`
Expected: `1 passed`. A failure at `routeDrawn` with a visible straight line means the browser's Geoapify call failed (check `VITE_GEOAPIFY_API_KEY` in the preview build).

Then mark the test session as internal so it does not count in the metric: the run's guest row is the newest one —
`./backend/script.demo.local.sh query "update guests set is_internal = true where id = (select id from guests order by created_at desc limit 1)"` (ask first: it writes to the remote database).

- [ ] **Step 6: Commit** (after approval)

```bash
git add webapp/src/Menucomponents/utils/geoapify.ts webapp/playwright.smoke.config.ts webapp/playwright.config.ts webapp/e2e/guest-demo.smoke.spec.ts webapp/package.json
git commit -m "chore: remove hardcoded geoapify key file and add deployed guest smoke test"
```

---

### Task 17: Documentation

**Files:**
- Modify: `CLAUDE.md`, `CHANGELOG.md`, `docs/API.md`

- [ ] **Step 1: `CLAUDE.md`** — replace the line

```
- **Auth / DB:** Supabase — not in scope for current phase, do not scaffold yet
```

with

```
- **Auth / DB:** Supabase (accounts, profile, push; unchanged, do not alter its schema or data without approval). Under `DEMO_MODE` the app uses the Railway demo Postgres instead (psycopg + Alembic in `migrations/postgres/`); guests have no account.
```

In "Current Scope", replace `- Supabase auth or database integration` under "Out of scope" with `- New Supabase tables or schema changes (the guest demo uses the Railway demo Postgres)`, and add to "In scope": `- Guest demo behind `DEMO_MODE`: `/config`, guest identity (`X-Guest-Id`), `/feedback`, `/events``. In "Tech Stack" leave the other lines as they are.

- [ ] **Step 2: `docs/API.md`** — add a section "Guest demo" documenting, with request and response bodies copied from the spec's section 6.2: `GET /config`, `POST /feedback`, `POST /events`, the `X-Guest-Id` / `X-Internal` headers, the `raw_wait` and `predicted` fields on `GET /facilities`, and the 429 busy body `{"code": "busy", "retry_after": <seconds>}` on `POST /chat/message`.

- [ ] **Step 3: `CHANGELOG.md`, Sprint 20** — tick every scope box this plan completed; under "Phase 0" leave item 3 (worker redeploy) as deferred; add a "Delivered" list with one line per task (1–16), the note that rotation of the Geoapify key was requested (and its status), the cause and fix found in Task 15, and the three approved-design deviations recorded in the spec (purge at session level, automatic location fallback, guest branch inside `AuthProvider`).

- [ ] **Step 4: Refresh the graph and run everything once more**

Run: `graphify update .`
Run: `cd backend && doppler run -- python -m pytest -q` → all pass.
Run: `cd webapp && npx tsc -b && npm run lint && npm run test` → all pass.

- [ ] **Step 5: Commit** (after approval)

```bash
git add CLAUDE.md CHANGELOG.md docs/API.md
git commit -m "docs: document the guest demo and update sprint 20 changelog"
```

---

## After the plan

1. `/end-sprint` opens the PR to `preview` (never `main` directly).
2. After the merge: redeploy the Railway worker, verify its three sinks, re-run the bad-data cleanup (deferred Phase 0 item 3) — each with the user's go-ahead.
3. Set `DEMO_MODE=true` and `DEMO_INTERNAL_TOKEN` in Doppler for the production API only when the user decides to open the demo.

## Skills applied

| Skill | Where |
|---|---|
| clean-architecture | SQL only in `guest_store` / `demo_db`; routers call services; `get_actor` is the one identity boundary |
| pragmatic-programmer | `demo_mode()` as a reversible switch; contracts written once in `shared/types.ts` + `models.py`; tracer path proven by Task 8 Step 7 before any UI |
| clean-code | small modules with one job; pure functions (`resolveDemoCoords`, `busyMessage`, `formatWaitLabel`) carry the logic and the tests |
| supabase-postgres-best-practices | pooled connections, indexed foreign keys, partial unique index for event de-duplication, least-privilege grants with RLS on |
| release-it | pool and statement timeouts, fail-open limiter with a Sentry warning, deep `/health`, additive migration, flag rollback |
| superpowers:test-driven-development | every logic task starts with a failing test |
