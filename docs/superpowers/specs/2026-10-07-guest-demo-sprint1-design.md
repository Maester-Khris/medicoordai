# Guest demo, sprint 1 — design

Date: 2026-10-07 · Branch: `feat/guest-demo-core` · Sprint 20
Status: design approved in chat on 2026-10-07 (four sections). Implementation plan:
[`docs/superpowers/plans/2026-10-07-guest-demo-sprint1.md`](../plans/2026-10-07-guest-demo-sprint1.md)

Inputs: `CHANGELOG.md` (Sprint 20), `artifacts/2026-10-04-demo-launch-decisions.md` (local),
Phase 0 work already on this branch (Alembic 0001–0003, worker rewrite, Geoapify gap-fill).

---

## 1. Intent

A public demo that needs no sign-in: a visitor describes symptoms in the chat, gets a facility
recommendation, and sees the route drawn on the map. Its purpose is evidence of real use.

- **Metric:** share of guest sessions that reach a drawn route. Counter-metric: thumbs-down rate.
- **Line in the sand (first 10 guest sessions):** at least 60% reach a route and at least 5 leave
  feedback. Under 30% reaching a route means onboarding is fixed before anything else.
- **Ships on `main` behind `DEMO_MODE`.** With the flag off, today's behavior is unchanged.

## 2. Decisions

| # | Decision | Chosen | Rejected |
|---|---|---|---|
| D1 | Spec/plan shape | One spec, one plan, three milestones (backend, frontend, hardening) | Two or three specs |
| D2 | Guest identity | Client-generated UUID in `localStorage`, sent as `X-Guest-Id` | Server-issued signed token |
| D3 | Supabase path | Both paths kept; `DEMO_MODE` selects the demo Postgres path inside the three services | Removing the Supabase data code now |
| D4 | Returning guests | See their last 5 sessions (same browser only) | Fresh start on every visit |
| D5 | Rate-limit store | Existing Redis, fixed 10-minute window, fails open | In-process counters; Postgres counts |
| D6 | Limiter scope | `POST /chat/message` only (the call that costs LLM money) | Every route |

Consequences accepted with D2 and D4: a new device, a private window or cleared storage is a new
guest with no history; there is no recovery; "guest" in the metric means "browser". The per-guest
limit can be dodged by clearing storage, so the per-IP limit is the real guard.

## 3. Scope

**In:** guest identity, `DEMO_MODE`, `/config`, demo data layer (psycopg), guest tables, rate
limit and the "busy" message, feedback, three events, 30-day purge, `raw_wait`/`predicted` in the
API and the UI, hidden sign-in/onboarding/push prompts, downtown-Toronto fallback, only the drive
mode visible, starter prompts, 911 notice, disclosure page, `/app` 404, removal of the hardcoded
Geoapify key file, deployed smoke test, `CLAUDE.md` and changelog.

**Out:** real cycle/transit/walk routing (sprint 2), LiteLLM gateway (sprint 2 or 3), moving the
browser's Geoapify routing calls to the backend (sprint 2), Supabase RLS fix, `/facilities/nearby`
repair, accounts/push/profile for guests, load and A/B testing, any Supabase schema or data change.

**Depends on, not part of this spec:** the rewritten wait-time worker is redeployed after the
merge to `preview`, then the bad-data cleanup is re-run. Until then the demo database holds test
wait-time rows and Redis holds the old worker's output.

## 4. Architecture

```
browser ── X-Guest-Id ──► FastAPI
  /config  (public)          │  get_actor ── DEMO_MODE on ─► guest (uuid, upserted in guests)
  /facilities (public)       │             └─ DEMO_MODE off ► Supabase JWT user (as today)
  /chat/*  /feedback /events │
                             ├─ services/{facilities,wait_times,chat}.py
                             │     DEMO_MODE on ─► services/guest_store.py ─► demo_db.py (psycopg pool)
                             │     DEMO_MODE off ► db.py (Supabase REST)            └► Railway Postgres
                             ├─ services/rate_limit.py ─► Redis (also the wait-time cache)
                             └─ LLM (Groq, unchanged)
browser ──► Geoapify routing (unchanged; key from VITE_GEOAPIFY_API_KEY)
```

`DEMO_MODE` is read through one function, `config.demo_mode()`. The three services branch on it;
routers and the LLM agent do not know which store they use. SQL lives only in
`services/guest_store.py` and the two demo read functions.

## 5. Data model (Alembic revision 0004)

All ids are `uuid` (`gen_random_uuid()`), except `guests.id` (supplied by the client) and
`events.id` (identity).

| Table | Columns | Notes |
|---|---|---|
| `guests` | `id`, `created_at`, `last_seen_at`, `is_internal bool default false` | no IP, no user agent |
| `sessions` | `id`, `guest_id → guests`, `title`, `created_at`, `updated_at` | index `(guest_id, updated_at desc)` |
| `messages` | `id`, `session_id → sessions on delete cascade`, `guest_id → guests`, `role in (user, assistant)`, `content`, `created_at` | index `(session_id, created_at desc)` |
| `feedback` | `id`, `guest_id → guests`, `session_id`, `message_id unique`, `thumb in (up, down)`, `comment ≤ 2000 chars`, `created_at`, `updated_at` | `session_id`/`message_id` carry no foreign key so the row survives the purge |
| `events` | `id`, `guest_id → guests`, `session_id null`, `type in (session_started, recommendation_shown, route_drawn)`, `created_at` | unique `(session_id, type)` where `session_id` is not null: one event of a type per session |

**Roles.** `medicoord_app` gains: `guests` select/insert/update; `sessions`
select/insert/update/delete; `messages` select/insert; `feedback` select/insert/update; `events`
select/insert. It still cannot truncate or create objects, and cannot delete anywhere except
`sessions`. `medicoord_worker` gets nothing on the new tables. RLS is enabled on all five tables
with explicit per-command policies for the app role, as in revision 0002.

**Isolation between guests** is enforced in the SQL (`where guest_id = …`), not by RLS: the
backend connects as one role. Every statement that touches a session or message carries the
guest id.

**Purge (changed from the approved wording).** The approved design said "delete from `messages`".
A session title is the first 50 characters of the first message, so it is chat text too. The
purge is therefore `delete from sessions where created_at < now() - interval '30 days'`; messages
go with it by cascade. That is why the app role has delete on `sessions` and not on `messages`.
`feedback` and `events` rows are kept.

## 6. Backend behavior

### 6.1 Identity

`get_actor` is a FastAPI dependency used by every `/chat` route and by `/feedback` and `/events`.

- `DEMO_MODE` off: it behaves exactly as `get_current_user` (Supabase JWT, 401 without one).
- `DEMO_MODE` on: it reads `X-Guest-Id`, rejects anything that is not a UUID with 400, upserts the
  `guests` row (`last_seen_at = now()`), and returns an object with `id`, `email = None`,
  `is_guest = True`. A database failure returns 503.
- `X-Internal: <token>` equal to env `DEMO_INTERNAL_TOKEN` (constant-time compare) sets
  `guests.is_internal`; it is never unset. The browser picks the token up from `?internal=<token>`
  once and keeps it in `localStorage`. (The approved wording said `?internal=1`; the browser cannot
  know the secret, so the URL carries it.)
- A newly created guest triggers the purge, at most once per hour (Redis `SET NX EX 3600`). If
  Redis is down the purge runs anyway (it is idempotent).

The approved design said "middleware". It is a dependency instead: it needs a database call, and
Starlette's `BaseHTTPMiddleware` cannot raise FastAPI HTTP errors cleanly (see the existing
comment in `middleware/auth.py`). Behavior is the same.

CORS must allow the `X-Guest-Id` and `X-Internal` request headers.

### 6.2 Endpoints

| Endpoint | Auth | Behavior |
|---|---|---|
| `GET /config` | none | `{demo_mode, starter_prompts, downtown_fallback: {lat, lng}, modes_enabled}`. With the flag off: `demo_mode: false`, all four modes. Starter prompts come from env `DEMO_STARTER_PROMPTS` (JSON array) or built-in defaults. |
| `POST /feedback` | guest | `{session_id, message_id, thumb, comment?}` → 204. One row per message; a second post updates it. 404 if the message is not an assistant message of that guest and session, or if the flag is off. |
| `POST /events` | guest | `{type: "route_drawn", session_id}` → 204. Only `route_drawn` is accepted from the client. 404 if the session is not the guest's, or the flag is off. |
| `GET /facilities` | none | each facility gains `raw_wait: string \| null` and `predicted: boolean`. `wait_minutes` stays (null for a predicted range). |
| `/chat/*` | `get_actor` | unchanged contract. `Message.user_id` and `Session.user_id` carry the guest id. |
| `GET /health` | none | adds `demoMode` and, when on, `demoDb: ok \| unreachable`. |

Server-side events: `session_started` when a guest creates a session, `recommendation_shown` when
a reply carries a recommended facility. Event writes are best-effort and never fail the request.

For guests the chat route skips the Supabase profile lookup.

### 6.3 Rate limit and "busy"

- Applies in demo mode to `POST /chat/message`: 10 per guest and 30 per IP per fixed 10-minute
  window, counted with Redis `INCR` + `EXPIRE`.
- The IP is taken from `X-Real-IP`, else the right-most `X-Forwarded-For` entry, else the socket.
  It is hashed (SHA-256) before it is used as a Redis key and lives 10 minutes. It is never
  written to Postgres or logs.
- Over the limit: HTTP 429, body `{"code": "busy", "retry_after": <seconds>}`, header `Retry-After`.
- An LLM provider error with status 429 maps to the same body with `retry_after: 60`.
- Redis unavailable: the limiter allows the request and reports a warning to Sentry.

### 6.4 Data layer

`demo_db.py` owns one `psycopg_pool.ConnectionPool` built from `POSTGRES_DB_URL_APP`
(min 1, max 5, 5 s acquire timeout, `statement_timeout` 5 s, dict rows). It is opened in the
FastAPI lifespan when the flag is on and closed on shutdown. New dependency: `psycopg_pool`.

`services/wait_times.py` keeps its cache-aside shape: Redis hash first; on a miss the demo path
reads the `wait_times` table instead of the Supabase RPC. It now returns `raw_wait` and
`predicted` with the minutes.

`place_id` holds Google ids (old rows) and Geoapify ids (gap-fill). Nothing in the backend or the
frontend reads it, and this sprint adds no reader.

## 7. Frontend behavior

- **Bootstrap.** `lib/config.ts` fetches `/config` once. `AuthProvider` keeps its single context:
  in demo mode it sets `user = {id: guestId}` and `isGuest = true` instead of starting Supabase
  auth. The thirteen `useAuth()` consumers keep working because `user` is truthy. (The approved
  wording was "a `GuestProvider` replaces `AuthProvider`"; one provider with a guest branch avoids
  touching every consumer.) If `/config` fails, the app falls back to non-demo behavior.
- **API calls.** `apiFetch` sends `X-Guest-Id` (and `X-Internal` if present) and does not ask
  Supabase for a token.
- **Hidden for guests.** Sign-in and sign-up buttons, `UserMenu`, profile and sign-out drawer
  items, the onboarding overlay, the install and push prompts, and the profile query.
  `/setup`, `/profile` and `/sandbox` redirect to `/app`.
- **Location.** In demo mode, when no position is available (denied, timeout, unsupported) or it
  lies outside the Toronto box (lat 43.58–43.86, lng −79.64 to −79.12), the request uses
  `downtown_fallback` and the chat shows "Using downtown Toronto as your location". The
  location-blocked modal gets a "Continue with downtown Toronto" button. (Approved wording: a
  button sets the anchor. The fallback is automatic with a visible notice because the three
  screens each hold their own geolocation state; the button remains as the way to dismiss.)
- **Modes.** Only modes in `modes_enabled` are shown: the map's Drive/Cycle/Transit switch, the
  mobile transit grid and the triage card's chips all reduce to Drive.
- **Starter prompts.** Chips come from `/config`; tapping one sends it.
- **Notice.** "Not medical advice. In an emergency call 911." is always visible under the chat
  input, in both modes.
- **Feedback.** Thumbs up/down under the recommendation; thumbs-down opens an optional text box.
- **Busy.** A 429 shows "MediCoord is busy right now. Try again in about N minute(s)." and
  disables sending until then. It is not styled as an error.
- **Wait times.** The facility popup shows `42 min wait`, or `45m–2h (predicted)`, or nothing.
- **Event.** `route_drawn` is posted once per session when real road geometry arrives from
  Geoapify. The straight-line fallback does not count.
- **Disclosure page.** States what is stored (chat text for 30 days, feedback and events kept,
  a random browser id, no IP addresses, no account) and how to ask for deletion.
- **Removed.** `webapp/src/Menucomponents/utils/geoapify.ts` (hardcoded key, no importers).

## 8. `/app` 404

Diagnosis comes first; the fix follows the cause. Hypotheses, most likely first:

1. The Vercel project's root directory is not `webapp/`, so `webapp/vercel.json` (the SPA
   rewrite) is ignored. Prerendered routes still work because they exist as files.
2. `cleanUrls` plus the prerendered folders shadows the catch-all rewrite for some paths.
3. The production alias points at an older deployment.

## 9. Error handling

| Failure | Behavior |
|---|---|
| Missing or malformed `X-Guest-Id` | 400 |
| Session or message id that is not a UUID, or not the guest's | 404 |
| Demo database unreachable | 503 on guest routes; `/health` reports it; `/facilities` serves its cache |
| Redis down | limiter allows; wait times fall back to the table; purge still runs |
| Event write fails | logged, request succeeds |
| LLM quota | 429 busy |
| Other LLM failure | existing fallback reply with the 911 line |
| `/config` unreachable | frontend behaves as non-demo |

## 10. Testing

- **Backend unit tests:** `get_actor` (both modes, bad ids), rate limiter (window, both limits,
  Redis down), busy mapping, `/config`, `/feedback`, `/events`, wait-detail annotation.
- **Store tests** against the local rehearsal Postgres (`medicoord-demo-pg`, skipped when it is not
  running): ownership checks, feedback upsert, event de-duplication, purge.
- **Migration:** 0004 rehearsed locally, then applied remotely; `verify` extended to the new grants.
- **Frontend unit tests (Vitest, no new packages):** guest id, config cache, location fallback,
  wait label, mode filter.
- **Acceptance:** one Playwright run against a deployed preview: landing → starter prompt →
  recommendation → route drawn (`POST /events` returns 204) → feedback (`POST /feedback` 204).

## 11. Rollout and rollback

1. Apply 0004 to the demo database (additive; old code is unaffected).
2. Set `DEMO_MODE=true`, `DEMO_INTERNAL_TOKEN`, and optionally `DEMO_STARTER_PROMPTS` in Doppler
   for the Railway API. `POSTGRES_DB_URL_APP` is already there.
3. Deploy backend, then frontend (the frontend reads the flag from `/config`; no build variable).
4. Run the smoke test against the preview.
5. Rotate the Geoapify key that was hardcoded.

Rollback: `DEMO_MODE=false` restores today's behavior without a deploy of the frontend.

## 12. Risks

- The per-guest limit is easy to dodge; the per-IP limit and Groq's own quota are the real caps.
- `VITE_GEOAPIFY_API_KEY` stays in the browser bundle until sprint 2.
- The route metric depends on the browser's Geoapify call succeeding.
- Wait times are only trustworthy after the worker redeploy.
- A quota error leaves the user's message stored without a reply; a retry stores it again.
- If `/config` fails on the demo site, visitors briefly see the sign-in UI.

## 13. Skills that shaped this design

| Skill | Where it applied |
|---|---|
| clean-architecture | SQL confined to `guest_store`/`demo_db`; routers depend on services, not on a store |
| pragmatic-programmer | `DEMO_MODE` as a reversible switch; one authoritative `/config`; no abstraction layer for one extra store |
| clean-code | small single-purpose modules (`rate_limit`, `retention`, `guest_store`); null-object guest user instead of null checks |
| supabase-postgres-best-practices | pooled connections, indexed foreign keys, least-privilege grants, RLS on with explicit policies |
| release-it | timeouts on the pool and statements, fail-open limiter, deep health check, flag-based rollback |
