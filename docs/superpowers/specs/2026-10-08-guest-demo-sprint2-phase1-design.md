# Guest Demo Sprint 2, Phase 1: backend routing, real travel modes, proximity fix

Date: 2026-10-08 · Branch: `feat/demo-user-experience` · Sprint 21

Inputs: `CHANGELOG.md` (Sprint 21), `docs/superpowers/specs/2026-10-07-guest-demo-sprint1-design.md`,
the Geoapify probe run on 2026-10-08 (section 2).

Phase 2 of the sprint (latency histograms, pool and rate-limit variables, load tests) has its own
spec, written after this one ships. Nothing in this document depends on it.

## 1. Goal

A guest picks how they travel and gets a real route and a real travel time for that mode. The map
filters work, including the distance filter. All routing runs on the backend, so it can be timed
later and the Geoapify key is no longer in the browser bundle.

**Done when**, on the `preview` deployment under `DEMO_MODE`:

1. The browser makes no request to `api.geoapify.com` and the built bundle does not contain a
   Geoapify key.
2. Car, bike, walk and bus each draw a route computed for that mode, with that mode's time.
3. No travel time shown anywhere in the UI is a multiplier or a speed guess; a time is either from
   `POST /routes` or absent.
4. Picking a radius chip filters the map (today `GET /facilities/nearby` returns 500).
5. A guest sees no link to the sandbox.
6. The deployed smoke suite passes with three new scenarios (section 9).

## 2. Evidence the design rests on

Probe from downtown Toronto (43.6532, -79.3832) to three hospitals, 2026-10-08, one run:

| Geoapify mode | Route Matrix | Routing (single route) | Sunnybrook | Scarborough General |
|---|---|---|---|---|
| `drive` | 200, ~1.1 s | 200, ~0.9 s | 18 min | 23 min |
| `bicycle` | 200, ~0.9 s | 200, 0.6–1.1 s | 34 min | 76 min |
| `walk` | 200, ~1.1 s | 200, 0.5–1.0 s | 145 min | 278 min |
| `transit` | **400, mode rejected** | 200, **~2.8 s** | 47 min | 66 min |
| `approximated_transit` | **400, mode rejected** | 200, 1.1–1.3 s | 39 min | 64 min |

Not verified: that `transit` uses real timetables (the times are plausible and differ from the
approximated mode, nothing more). One run is not a latency measurement; Phase 2 measures it.

What the code does today:

- `backend/services/proximity.py` picks the `TRIAGE_TOP_N_FACILITIES` (default 3) nearest eligible
  facilities by Haversine distance. They reach the browser as `recommended_facility` plus
  `nearby_facilities`.
- `webapp/src/hooks/useTriageState.ts` calls Geoapify Route Matrix then Routing from the browser,
  both hardcoded to `mode=drive`, using `VITE_GEOAPIFY_API_KEY`.
- Fake travel times exist in three places: `RoadRouteLayer.tsx` (`getScaledEta`: bike ×2.5,
  bus ×1.8), `TriageCard.tsx` (`bikeMin` at 12 km/h, `walkMin` at 5 km/h),
  `mobile/TransitModeGrid.tsx` (cycle ×2.5, walk ×6).
- The travel mode is local state in `MapPanel.tsx`; the route state lives in `useTriageState`,
  used by `Home.tsx` (desktop) and `MobileLayout.tsx`.
- `GET /facilities/nearby` (`backend/main.py`) always calls the Supabase function
  `nearby_facilities`, which references a column that does not exist. It returns 500. The radius
  chips call it through `useProximitySearch`; on failure the map silently shows every facility.
- The `events` table accepts three types, one row per type per session, with no payload columns.
- `/sandbox` is behind `ProtectedRoute`, which sends guests to `/app`. Links to it remain in
  `WebNavBar.tsx`, `LandingPage.tsx` and `ForInvestorsPage.tsx`.
- Doppler: `stg` and `prd` have `GEOAPIFY_API_KEY`; the local config `dev_personal` has only
  `VITE_GEOAPIFY_API_KEY`.

## 3. Decisions

| # | Decision | Why |
|---|---|---|
| D1 | Modes: car, bike, walk, bus. Bus uses Geoapify `transit`. | Option A; the probe returned plausible Toronto transit routes. |
| D2 | One code path: one Routing call per candidate, all candidates in parallel, for every mode. No Route Matrix call. | Matrix rejects transit. One path means one set of tests. Each call returns time, distance and shape, so the browser holds the shape for every candidate. Cost: three Geoapify calls per request instead of two. |
| D3 | Parallelism is `asyncio.gather` on one `httpx.AsyncClient`, not a thread pool. | The calls are network waits. The thread pool is what the synchronous database calls use and is the likely bottleneck in Phase 2. |
| D4 | The backend resolves facility coordinates from its own facility cache; the request carries facility ids, not coordinates. | The endpoint cannot be used to route between arbitrary points on our quota. |
| D5 | A mode change re-ranks the same candidates by the new mode's time. It does not search for new facilities. | "Re-selects among the top candidates" in the sprint scope. |
| D6 | The browser keeps each mode's result for the current recommendation. Returning to a mode already seen makes no request. | Cheap, and makes the trade-off in D2 pay off twice (facility switch and mode return). |
| D7 | The straight-line fallback stays and still does not count as a route drawn. | Unchanged from Sprint 20. |
| D8 | Migration 0005 adds `mode` and `duration_ms` to `events` and a repeatable `mode_changed` type. | Guest analytics are read from the database. In-process metrics reset on deploy and Grafana access is unconfirmed. |
| D9 | Proximity in demo mode filters the in-memory facility cache with the existing `haversine_km`. | 308 facilities; no SQL, no PostGIS, no migration. |
| D10 | The non-demo Supabase path of `/facilities/nearby` is left as it is (broken). | Out of scope; resolved by the later Postgres move. |

## 4. API contract

Types are added to `shared/types.ts` first, then mirrored in `backend/models.py`.

### 4.1 `POST /routes`

Request:

```ts
export interface RoutesRequest {
  origin:       { lat: number; lng: number }
  facility_ids: string[]        // 1 to 3, unique
  mode:         TravelModeKey   // "car" | "bike" | "bus" | "walk"
}
```

Response 200:

```ts
export interface CandidateRoute {
  facility_id: string
  eta_minutes: number | null            // null when this candidate has no route
  distance_km: number | null
  geometry:    [number, number][] | null // [lat, lng] pairs, ready for Leaflet
}

export interface RoutesResponse {
  mode:                TravelModeKey
  routes:              CandidateRoute[]   // same order as facility_ids
  fastest_facility_id: string | null      // lowest eta_minutes among routed candidates
}
```

Status codes:

| Case | Status |
|---|---|
| At least one candidate routed | 200 |
| `facility_ids` empty, more than 3, or duplicated; `mode` not in `modes_enabled`; origin out of range (lat −90..90, lng −180..180) | 422 |
| A facility id is not in the facility cache | 404 |
| Guest over the routes rate limit | 429 with the existing `BusyResponse` body |
| Every candidate failed or timed out | 502 |
| `GEOAPIFY_API_KEY` not set, or the facility cache is empty | 503 |

Auth: the existing `get_actor` dependency (guest under `DEMO_MODE`, signed-in user otherwise).

Mode mapping, in one place (`services/routing.py`): `car→drive`, `bike→bicycle`, `walk→walk`,
`bus→transit`.

Geometry: Geoapify returns `MultiLineString` or `LineString` with `[lng, lat]`. The backend
flattens the legs and swaps to `[lat, lng]`. `eta_minutes` is `round(time / 60)`, `distance_km`
is rounded to one decimal.

### 4.2 `POST /events` (changed)

```ts
export interface GuestEventRequest {
  type:         "route_drawn" | "mode_changed"
  session_id:   string
  mode?:        TravelModeKey   // required for mode_changed; sent with route_drawn
  duration_ms?: number          // mode_changed only: click to route redrawn, 0..120000
}
```

`route_drawn` stays at most one row per session (the first route drawn, with its mode).
`mode_changed` can repeat. A `mode_changed` without `mode` is a 422. A `route_drawn` without
`mode` is still accepted, so a browser running the previous bundle keeps working during a deploy.

### 4.3 `GET /facilities/nearby` (demo branch)

Parameters and response shape (`NearbyFacilityResult`) are unchanged. Under `DEMO_MODE`:

- Source: the facility cache. Distance: `haversine_km` × 1000, rounded to metres.
- Keep facilities with `distance_m <= min(radius_m, 50000)` and, when `category` is given, that
  category. Sort by distance, keep the first 50.
- `eta_walk_min`, `eta_transit_min`, `eta_drive_min`: `round(distance_m / speed / 60)` with the
  speeds the Supabase function used (1.4, 6.0 and 11.0 m/s). These three fields are not displayed
  anywhere in the web app today; they are filled to keep the contract.
- `is_operational` is `true` (the cache only holds operational facilities). `phone` comes from the
  cache row.
- `max_wait_minutes` is applied with the existing `apply_wait_filter`, as now.
- Empty cache: 503.

### 4.4 `/config`

`modes_enabled` under `DEMO_MODE` becomes `["car", "bike", "bus", "walk"]` (`DEMO_MODES` in
`backend/config.py`).

## 5. Backend design

| Unit | Responsibility | Depends on |
|---|---|---|
| `services/routing.py` (new) | Mode mapping; one Geoapify Routing call; fan-out over candidates; pick the fastest. No FastAPI imports. | `httpx`, `GEOAPIFY_API_KEY` |
| `routers/routes.py` (new) | Validate the request, resolve facility ids from the cache, apply the rate limit, map outcomes to status codes. | `services/routing.py`, `cache`, `services/rate_limit.py`, `middleware/auth.get_actor` |
| `services/proximity.py` (extended) | `find_facilities_within(lat, lng, radius_m, category)` for the demo branch. | `cache` |
| `main.py` | Register the router; demo branch in `facilities_nearby`. | above |
| `services/guest_store.py` | `record_event` stores `mode` and `duration_ms`. | `demo_db` |
| `services/rate_limit.py` | `check_rate_limit` takes a bucket name and its two limits. | Redis |

`services/geoapify_shadow.py` is not touched: it is the Sprint 17 measurement side-channel and
has a different purpose.

**Routing behaviour**

- One `httpx.AsyncClient` per request, shared by the candidate calls, timeout 8 seconds per call
  (connect 3 s). The slowest observed call was 2.9 s.
- `asyncio.gather(..., return_exceptions=True)`: one failing candidate yields nulls for that
  candidate and does not cancel the others. No retry: the browser already has a fallback, and a
  retry would double a slow request.
- A failure is logged once per candidate as `routing_candidate_failed` with the mode, the
  facility id and the error type. The API key never appears in a log line or an error body.
- `fastest_facility_id`: lowest `eta_minutes`; ties go to the earlier position in `facility_ids`.

**Rate limit**

`check_rate_limit(guest_id, ip, *, bucket="chat", guest_limit=GUEST_LIMIT, ip_limit=IP_LIMIT)`.
Keys become `rl:{bucket}:guest:…` and `rl:{bucket}:ip:…`. Routes use bucket `routes` with 60 per
guest and 180 per IP per 600 s (constants `ROUTES_GUEST_LIMIT`, `ROUTES_IP_LIMIT`): six times the
chat limit, because one conversation can change mode several times. Renaming the chat keys
resets the chat counters once at deploy; they live 10 minutes, so this is harmless. Only guests
are limited, as for chat. Phase 2 turns the limits into environment variables.

**Migration 0005** (`migrations/postgres/versions/`, same style as 0004)

- `alter table events add column mode text null check (mode in ('car','bike','bus','walk'))`
- `alter table events add column duration_ms integer null check (duration_ms between 0 and 120000)`
- Replace the type check so it also allows `'mode_changed'`.
- Replace the unique index `events_session_type_key` with the same index restricted to
  `type <> 'mode_changed'`.
- A check: `duration_ms is null or type = 'mode_changed'`.
- Downgrade deletes `mode_changed` rows, then restores the 0004 objects.
- No grant change: the app role already has insert and select on `events`.

`record_event`'s `on conflict` clause must name the new index predicate, or Postgres rejects it.

## 6. Frontend design

| Unit | Change |
|---|---|
| `lib/routesClient.ts` (new) | `fetchRoutes(origin, facilityIds, mode)` through `apiFetch`; returns `RoutesResponse` or `null` on any failure. Never throws. |
| `hooks/useTriageState.ts` | Owns the travel mode, the per-mode result cache, and three actions: `applyTriageResult`, `changeMode`, `selectFacility`. The two direct Geoapify functions and `GEOAPIFY_KEY` are deleted. |
| `lib/guestEvents.ts` | `postRouteDrawn(sessionId, mode)`; new `postModeChanged(sessionId, mode, durationMs)`. |
| `components/map/MapPanel.tsx` | Receives `travelMode` and `onModeChange` as props; local state removed; walk button added. |
| `components/map/layers/RoadRouteLayer.tsx` | `getScaledEta` deleted. Alternatives are drawn with their real geometry when present. |
| `components/triage/TriageCard.tsx` | `bikeMin` and `walkMin` deleted. The mode chips show the time for the active mode and a dash for the others; clicking a chip changes mode. Rows under "Other nearby options" call `selectFacility`. |
| `components/mobile/TransitModeGrid.tsx` | Multipliers deleted; a bus cell is added; same rule (time for the active mode, dash for the others). |
| `Home.tsx`, `MobileLayout.tsx`, `FacilityCardPanel.tsx` | Pass `travelMode`, `changeMode`, `selectFacility` down. |
| `WebNavBar.tsx`, `LandingPage.tsx`, `ForInvestorsPage.tsx` | The sandbox link is not rendered when `config.demo_mode` is true. |

**State** (`shared/types.ts`)

```ts
export interface RouteResult {
  facilityId: string
  etaMinutes: number
  distanceKm: number
  geometry:   [number, number][] | null   // new
}

export interface TriageUIState {
  // existing fields unchanged
  travelMode:   TravelModeKey   // new, "car" on every new recommendation
  routeLoading: boolean         // new, true while a routes request is in flight
}
```

`roadGeometry` stays in the state and is always the geometry of the recommended facility's route,
so `RoadRouteLayer` keeps reading the same field.

**Behaviour**

- `applyTriageResult`: sets the candidates, resets the mode to `car` and the cache, then requests
  routes for `car`. On success: store the routes, set the recommendation to
  `fastest_facility_id`, set `roadGeometry`, send `route_drawn` with the mode. On failure: no
  routes, straight-line fallback, no event.
- `changeMode(mode)`: no-op if it is the current mode or there are no candidates. Cache hit:
  apply the cached result, send nothing. Cache miss: record `performance.now()`, request, apply,
  then send `mode_changed` with the elapsed milliseconds after the state update, and `route_drawn`
  if no route had been drawn in this session yet (the sender already deduplicates per session). On failure: keep
  the previous mode and its route (the buttons do not move), send nothing.
- `selectFacility(id)`: if the current mode's routes contain that id with a geometry, set the
  recommendation and `roadGeometry` to it. No request, no event.
- A response that arrives for a recommendation or a mode that is no longer current is dropped
  (compare a request counter held in a ref).
- While `routeLoading` is true the mode buttons are disabled and the active one shows a busy
  state (`aria-busy`).

**Removal of the browser key**: `VITE_GEOAPIFY_API_KEY` is removed from the code, from
`webapp/.env*` examples and from the CI workflow if it appears there. Removing it from Doppler
and Vercel is a manual step for the owner after the deploy is verified.

## 7. Error handling

| Failure | Guest sees | Recorded |
|---|---|---|
| One candidate has no route | Routes for the others; that candidate shows no time | `routing_candidate_failed` log |
| All candidates fail, or 502/503/timeout | Straight line to the recommended facility, no time | Log; no `route_drawn` |
| Routes rate limit (429) | Straight line; mode stays where it was | — |
| Mode change fails | Previous mode and route stay | — |
| `/facilities/nearby` fails | As today: all facilities shown | Existing hook error state |
| `/events` fails | Nothing | Swallowed, as today |

## 8. Out of scope

- Phase 2: histograms, pool size and rate-limit environment variables, `pg_stat_statements`,
  load tests, profiling, Web Vitals.
- GraphRAG, the LiteLLM gateway, promotion to `main`.
- Searching for different facilities when the mode changes.
- Prefetching every mode at recommendation time (twelve Geoapify calls per recommendation).
- A shared, long-lived HTTP client and connection reuse (decided from Phase 2 measurements).
- The non-demo `/facilities/nearby` path and the Supabase function.
- The hackathon `OsrmRouteLayer.tsx`.

## 9. Testing

**Backend (pytest, Geoapify mocked with `httpx.MockTransport`; no network in unit tests)**

- `routing`: mode mapping for the four keys; geometry flattening and `[lat, lng]` order for
  `MultiLineString` and `LineString`; one candidate failing leaves the others intact; all failing;
  timeout; fastest selection and the tie rule; the API key absent from logs.
- `routes` router: each status code in 4.1; the rate limit applies to guests only; unknown
  facility id.
- `proximity`: radius boundary (inclusive), category filter, ordering, the 50 cap, empty cache.
- `facilities_nearby`: demo branch returns the contract shape; non-demo branch still calls the
  Supabase function (unchanged behaviour is asserted, not fixed).
- `guest_store` and the events router: `mode` stored on `route_drawn`; `mode_changed` repeats
  within a session; `route_drawn` does not; validation in 4.2.
- `rate_limit`: buckets do not share counters; the chat bucket keeps its limits.
- Migration 0005: upgrade and downgrade rehearsed on the local throwaway database, then the
  existing `verify` command.

**Frontend (vitest)**

- `routesClient`: success, HTTP error, network error all resolve without throwing.
- `useTriageState`: recommendation follows `fastest_facility_id`; mode change re-ranks; cache hit
  makes no request; failed mode change keeps the previous mode; stale response dropped;
  `selectFacility` swaps geometry without a request.
- `guestEvents`: `mode_changed` carries mode and duration; `route_drawn` once per session.

**End to end (deployed smoke suite, `webapp/e2e/*.smoke.spec.ts`)**

1. Mode change: after the first route, click Cycle; expect `POST /routes` 200, a route path
   present, a `mode_changed` event 204, and no request to `api.geoapify.com` during the test.
2. Filters: pick a category chip and a radius chip; expect `GET /facilities/nearby` 200 and fewer
   markers than before.
3. Sandbox: no sandbox link on `/` for a guest; opening `/sandbox` lands on `/app`.

The existing smoke scenario keeps passing unchanged apart from the routing request it waits on.

## 10. Rollout

1. `GEOAPIFY_API_KEY`: checked on 2026-10-08 with the Doppler CLI (names only). The `stg` and
   `prd` configs already have it; `dev_personal` (local development) does not. The owner adds it
   to `dev_personal` with the Doppler CLI before the backend tasks run locally.
2. Migration 0005 goes through `backend/script.demo.local.sh`, in the order used for 0001–0004:
   `--local migrate` then `--local verify` on the throwaway database (upgrade, downgrade, upgrade
   again), then `migrate` and `verify` on `medicoord-db-demo` through the admin tunnel.
   **It is not additive for the running API** (found on 2026-10-09 after applying it): the
   narrowed unique index no longer matches the `on conflict` clause of the 0004 insert, so the
   previous backend can no longer write any event row. Chat keeps working because event writes
   are best-effort, but events are lost. The migration must therefore be applied in the same
   window as the backend deploy, not ahead of it.
3. Migration and backend deploy together, then the web app: the new browser code needs
   `POST /routes`; the old browser code keeps working against the new backend (it sends
   `route_drawn` without a mode, which is still accepted).
4. Smoke suite against `preview`.
5. Owner removes `VITE_GEOAPIFY_API_KEY` from Doppler and Vercel.

## 11. Execution and review

The plan is executed by Gemini and reviewed by Claude in three batches:

1. Backend: contracts, migration 0005, routing service and router, rate-limit bucket, proximity
   branch, events.
2. Frontend: routes client, state hook, mode surfaces, events, sandbox links, key removal.
3. End-to-end scenarios, documentation (`docs/API.md`, `CHANGELOG.md`), final checks.

## 12. Design lenses used

| Skill | Where it shaped the design |
|---|---|
| clean-architecture | `services/routing.py` has no FastAPI imports; the router only translates and delegates (section 5). Facility ids, not coordinates, cross the boundary (D4). |
| pragmatic-programmer | One routing path instead of two (D2, orthogonality and DRY); the single rule "no time that did not come from `/routes`" removes three copies of the same guess (section 6). |
| clean-code | Small named actions in the state hook (`changeMode`, `selectFacility`); failures return `null` or nulls instead of throwing across the UI boundary. |
| release-it | Timeout on every outbound call, partial failure isolated per candidate, no retry storm, own rate-limit bucket, additive migration and deploy order (sections 5, 7, 10). |
| supabase-postgres-best-practices | Partial unique index and check constraints in migration 0005; no new grants (section 5). |
| test-driven-development | Every backend and frontend unit in section 9 is written test-first in the plan. |
