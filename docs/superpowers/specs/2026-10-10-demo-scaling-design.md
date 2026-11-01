# Guest Demo Sprint 3: demo scaling

Date: 2026-10-10 · Branch: `feat/demo-scaling` · Sprint 22

Inputs: `CHANGELOG.md` (Sprint 22 scope and decisions, Sprint 21 results), the Sprint 21 phase 2
report (`artifacts/perf/2026-10-10-phase2-report.md`, local), the research file
(`artifacts/research/2026-10-10-nearest-facility-lookup-and-request-batching.md`, local), and the
code reads taken on 2026-10-10 (section 2).

## 1. Goal

The API holds 1,000 to 2,000 chat turns in flight on the Sprint 21 box, degrades by refusing work
instead of queueing it, and can be scaled out by adding replicas. Every number quoted is measured
and its conditions are stated.

**What "1,000 to 2,000 concurrent chat turns" means here.** Turns in flight at the same moment
on the server. At 4.2 s per turn that is about 240 turns per second, which no demo-tier LLM quota
allows (about 480 LLM calls per second and 36 million tokens per minute, from Sprint 21's own
figures). So the claim has two parts, both reported:

- **Server capacity**, measured against a mock provider with the measured latency distribution.
- **Real ceiling**, measured against the real provider at whatever its quota allows, which also
  proves the mock is honest.

The sprint has seven phases with two owners (section 14):

- **Code, executed from the implementation plan** (phases 1 to 3): the map path, the chat turn,
  and facility recommendation with route drawing.
- **Preparation, harness, measurement and operations** (phases 0, 4, 5, 6): run by the engineer
  with the owner, because they need the tunnel, Railway, Doppler and judgement on live results.

**Done when**

1. A chat turn makes its LLM calls on the event loop through the providers' async clients; no
   thread is held for the length of an LLM call.
2. Conversation history is read from Postgres on every turn; the in-process chat cache is gone.
3. Past `MAX_TURNS_IN_FLIGHT` a turn gets the busy answer at once, and the chat shows a waiting
   state that retries by itself.
4. `/facilities` encodes its response once per data version and answers a matching
   `If-None-Match` with 304 without encoding or hashing; wait-time data is read from process
   memory, not from Redis per request.
5. A recommendation is chosen through the cell index and the load-aware score, and one Geoapify
   Routing call is made up front instead of three.
6. One report under `artifacts/perf/` holds: calibration of the mock against the real provider,
   the chat breakpoint, behaviour past the admission limit, the chosen database pool size and the
   reading behind it, a one-hour soak with memory, the new map breakpoint, Geoapify calls per
   1,000 guests before and after, lookup time at 304, 10k and 100k facilities, and the scaling
   ratio at 1, 2 and 4 replicas.
7. The 27-vignette triage check gives the same result before and after the chat changes.
8. Grafana Cloud receives the API's metrics, and python-api and Postgres run in US East.

## 2. Evidence the design rests on

| Fact | Source |
|---|---|
| Turn p50 is flat at about 4.2 s from 1 to 40 concurrent; a turn is two LLM calls at a mean of 2.2 s; the thread pool of 40 is the cap | Sprint 21 report, section 4 |
| Map endpoints break between 200 and 250 requests per second; 74.5% of thread time is one Redis read per request; JSON encoding is about 22% of CPU, done twice | Sprint 21 report, sections 2 and 3 |
| API to Redis is cross-region (US West to US East), 65 to 75 ms | Sprint 21 report, section 3 |
| Memory rose from 106 MB to 397 MB in the 13-minute chat run | Sprint 21 report, section 4 |
| The whole turn is blocking and runs on the thread pool in five places | `backend/routers/chat.py`, `send_message` |
| `BaseLLMClient.chat`, the fallback wrapper, the agent and the database pool are synchronous | `backend/llm/base.py`, `backend/llm/fallback.py`, `backend/services/llm_agent.py`, `backend/demo_db.py` |
| A new `LLMAgent`, and with it new provider clients, is built on every message | `backend/routers/chat.py`, `send_message` |
| History for the LLM comes only from the in-process cache, which is filled only by `GET /chat/sessions`; with no entry the agent gets an empty history, and the follow-up limit, which counts turns from that history, never fires | `backend/routers/chat.py`, `backend/cache_chat.py`, `backend/services/llm_agent.py` |
| Test B never calls `GET /chat/sessions`, so the cache stayed empty during the run in which memory grew | `backend/scripts/load/test_b.js` |
| `/facilities` serialises the list for the ETag, hashes it, then serialises it again, and sends `Cache-Control: no-cache` | `backend/main.py`, `facilities` |
| `/routes` makes one Geoapify Routing call per candidate, awaited together; the nearest-facility lookup is a pure-Python scan and sort | `backend/services/routing.py`, `backend/services/proximity.py` |
| Wait times are shown and can filter but do not influence which facility is recommended | `backend/services/facilities.py`, `backend/services/routing.py` |
| A busy answer already exists (`429`, `code: busy`, `retry_after`), used by the per-guest limit and for provider quota errors | `backend/services/rate_limit.py` |
| Geoapify: Routing is one credit per route; free plan 3,000 credits a day and 5 requests per second; limits are "soft" | research file, concern 4 |
| The async SDK clients cap connections by default: Groq at 100, OpenAI and Anthropic at 1,000 | read from the installed SDKs (groq 1.0.0, openai 2.45.0, anthropic 0.40.0), 2026-10-10 |
| Nearest-facility lookup, scan against cell index, mean of 200 lookups: 304 facilities 0.12 ms against 0.18 to 0.70 ms; 1,000 facilities 0.40 ms against 0.11 to 0.29 ms; 100,000 facilities 48 to 59 ms against 0.45 ms | measured locally with the plan's benchmark script, 2026-10-10 |

**Consequence of two of these rows.** The conversation cache was the first suspect for the memory
growth. It cannot be the cause in Test B. The cause is unknown; phase 0 finds it. Building
provider clients on every message is the next hypothesis, not a finding.

## 3. Decisions

Decisions 1 to 10 were taken on 2026-10-10 and are recorded with their reasons in `CHANGELOG.md`
(Sprint 22, Decisions). Decisions 11 to 17 were taken in the design session the same day.

| # | Decision | Why |
|---|---|---|
| 1 | Wait-time data held in API memory, reloaded on a short TTL with jitter | Removes the per-request Redis read; jitter stops replicas reloading together |
| 2 | Worker writes a "last successful run" key; ETag and `max-age` derive from it | Every instance, whenever started, gives the same answer |
| 3 | Facility list encoded once per data version, served as bytes | Removes the encoding cost instead of making it faster |
| 4 | No request batching window | The reason ride-hailing batches does not apply; costs more credits; adds seconds |
| 5 | Candidate lookup through an in-memory cell index | Cost depends on facilities nearby, not on how many exist |
| 6 | One route up front, others on demand | 3 Geoapify calls per guest become about 1; may be revisited |
| 7 | Load-aware choice for routine and moderate only | Avoids herding on 15-minute-old wait data; urgent and emergent get the fastest |
| 8 | Load counters in Redis, one per facility per minute, no locks | Shared across replicas with no request waiting on another |
| 9 | Travel-time cache in process | It only improves ranking; a Redis round trip is not worth it |
| 10 | Geoapify limiter with emergent first and a degraded answer | The vendor's rate is the real ceiling |
| 11 | Capacity proven against a mock provider, calibrated by a real run | The real quota cannot carry 1,000 turns in flight |
| 12 | Async for the LLM path only; database and Redis calls stay on the thread pool | LLM time is essentially the whole turn; the other calls hold a thread for milliseconds |
| 13 | History read from Postgres each turn, no cache | Correct on any replica and after a restart; Redis is farther away than the database |
| 14 | Admission control per process, immediate busy answer, no queue | No shared state; capacity adds up across replicas; overload is easy to reason about |
| 15 | Final numbers on the Sprint 21 box (1 worker, 1 vCPU, 1 GB, US West); a larger box only if one box misses 1,000 | Like-for-like comparison with Sprint 21 |
| 16 | At the end, python-api and Postgres move to US East | Next to Redis; done last so it does not disturb the comparison |
| 17 | Phases 1 to 3 executed from the plan in three review batches; the rest done directly | Product code is fully specified; the rest needs live systems |

Decision 13 replaces the carried item "conversation history out of process memory (Redis in front
of Postgres)".

## 4. Phase 0: preparation

1. **Staging back up.** `medicoordai-staging` at 1 worker, 1 vCPU, 1 GB, pointed at
   `feat/demo-scaling`. Test-only settings go on this service, never in Doppler `stg`.
2. **Load-test rows.** Delete the load-test guest rows from the demo database through the tunnel:
   dry run with counts, then apply. The non-internal guest row starting `8fe1df4f` is reported to
   the owner and left in place.
3. **Memory profile.** A staging-only setting (`MEMORY_PROFILE`) turns on `tracemalloc`; a short Test B run is taken
   with a snapshot at the start and at the end, and the top allocation sites by growth are
   recorded. The result goes into the report and decides whether phase 2 needs anything beyond
   what section 6 already does (clients built once per process).

## 5. Phase 1: the map path

### 5.1 Data version

- The worker writes `wait:last_run` (a UTC timestamp) at the end of every successful run.
- The API's data version is the pair (facility snapshot version, `wait:last_run`). The facility
  snapshot version is the ETag the facility cache already computes when it loads.

### 5.2 Wait times in memory

- One module holds the wait map and `wait:last_run` in process memory.
- One background task reloads it from Redis every `WAIT_CACHE_TTL_SECONDS` (default 30) plus a
  random jitter of up to 20% of that value, chosen at each reload. It is loaded once at startup.
- A reload that fails keeps the previous copy and logs a warning. With no copy at all, the
  endpoints behave as they do today when wait data is missing: facilities are returned without
  wait details.
- Requests only read the copy: no request triggers or waits for a reload.
- `/facilities`, `/facilities/nearby` and the recommendation score (section 7) read this module.
  Nothing on a request path calls Redis for wait data.

### 5.3 Encode once, serve bytes

- A bounded cache maps (data version, category, severity, max_wait_minutes) to (response bytes,
  ETag). Size limit 64 entries, least recently used evicted.
- The ETag is derived from the data version and the filter values, not from hashing the payload.
- Per request: build the key, compare `If-None-Match`, return 304 or the stored bytes. On a miss,
  build the list as today, encode once, store.
- Response headers: `ETag`, and `Cache-Control: max-age=N` where N is the number of seconds until
  `wait:last_run` plus 15 minutes, with a floor of `MAP_MIN_MAX_AGE_SECONDS` (default 30). When
  `wait:last_run` is absent, N is the floor.
- The 15-minute interval is one named constant shared with the worker's schedule.

### 5.4 Client

- `/facilities` sends `X-Wait-As-Of` (the `wait:last_run` timestamp), listed in the CORS exposed
  headers. The response body keeps its shape. The header is absent when `wait:last_run` is.
- The web app shows "Wait times as of HH:MM" from that header, and nothing when it is absent.
- No other client change: the browser honours the caching headers.

## 6. Phase 2: the chat turn

### 6.1 Async LLM path

- `BaseLLMClient.chat` becomes `async`. `GroqClient`, `AnthropicClient` and `OpenAIClient` use
  the SDKs' async clients. Behaviour is unchanged: same timeouts, same retry setting, the same
  single retry on Groq's tool-use glitch.
- `FallbackLLMClient` and `InstrumentedLLMClient` become async with the same semantics: one try
  per provider, no sleep, the same metrics and log lines.
- Each async client is given explicit connection limits from configuration
  (`LLM_MAX_CONNECTIONS`, default 2,000). The SDK defaults would be a hidden cap: 100 for Groq,
  1,000 for OpenAI and Anthropic.
- `LLMAgent.respond` and the methods it calls become async. Tool work that is in memory stays
  inline. A graph provider that does network I/O is called on the thread pool.
- The client chain and the agent are built once at startup and reused.
- The evaluation scripts call the agent through `asyncio.run` at their single call site.

### 6.2 History from Postgres

- The stores gain one function: the last `CHAT_HISTORY_MESSAGES` (default 20) messages of a
  session for a guest, oldest first. It runs on the thread pool like the other store calls.
- `send_message` reads history through it before saving the new user message.
- `backend/cache_chat.py` is deleted, with every import of it. `GET /chat/sessions` reads the
  store each time; `POST /chat/sessions/invalidate` stays as an endpoint that does nothing and
  returns success, so the current client keeps working.

### 6.3 Admission control

- A module `services/admission.py` holds the number of turns in flight in the process and offers
  one context manager. Entering when the count is at `MAX_TURNS_IN_FLIGHT` raises a dedicated
  exception; leaving always decrements.
- `send_message` enters it first, before the per-guest rate limit, so a refused turn does not use
  the guest's allowance. The refusal is the existing busy answer with
  `retry_after = ADMISSION_RETRY_SECONDS` (default 3) plus 0 to 2 seconds of jitter.
- `MAX_TURNS_IN_FLIGHT` defaults to 0, meaning no limit, until phase 5 sets it.
- Metrics: a gauge `chat_turns_in_flight` and a counter `chat_turns_rejected_total`.

### 6.4 Waiting state on screen

- A busy answer with `retry_after` of 10 seconds or less: the chat shows "High demand, retrying
  in N seconds", retries by itself, at most three times, then shows today's busy message for a
  minute.
- A longer `retry_after`: today's busy message.
- Both show "If this is an emergency, call 911".
- The guest's message stays in the input history and is not duplicated by a retry: the user
  message is saved by the server only on an admitted turn (admission runs before any write).

## 7. Phase 3: recommendation and route drawing

### 7.1 Cell index

- New dependency: `h3` (Python). Added to `requirements.txt`.
- Built when the facility snapshot changes: `cell → [facilities]` at resolution 8.
- Lookup: the guest's cell, then rings of neighbours, widening until at least
  `TRIAGE_TOP_N_FACILITIES` facilities accept the severity, then out to the ring count that is
  sure to contain everything as near as the farthest of them. Exact haversine on those
  candidates, top N kept.
- The index is used from 1,000 facilities. Below that the scan is as fast or faster (section 2),
  so today's 304 facilities are still scanned. A lookup the rings cannot guarantee (few matches,
  or all far away) also falls back to the scan, which is always correct.
- `find_nearest_facilities` and `find_facilities_within` keep their signatures and results; only
  how candidates are gathered changes. A facility snapshot with no rows gives an empty result as
  today.
- A benchmark script times scan against index on 304, 10k and 100k synthetic facilities.

### 7.2 Load-aware choice

- Applies when severity is `routine` or `moderate` and `LOAD_AWARE_ROUTING` is on (default on).
  For `urgent` and `emergent` the recommended facility is the one with the lowest estimated
  travel time, as today.
- Score per candidate, in minutes:
  `travel_minutes + wait_minutes + recent_assignments × LOAD_PENALTY_MINUTES[category]`.
  - `travel_minutes`: from the travel-time cache (7.4) when present, otherwise haversine distance
    over a fixed speed for the mode.
  - `wait_minutes`: from the in-memory wait map; a facility with no wait data contributes 0.
  - `recent_assignments`: section 7.3.
  - `LOAD_PENALTY_MINUTES`: a configured value per facility category.
- Candidates whose score is within `LOAD_SCORE_TIE_MINUTES` (default 5) of the best form the tie
  set; one is picked at random.
- The response says which facility is recommended and keeps the other candidates in score order.

### 7.3 Load counters

- At each recommendation: `HINCRBY load:{minute} {facility_id}|{instance_id} 1` and an expiry of
  `LOAD_WINDOW_MINUTES` (default 15) plus one minute. One hash per minute, so a refresh is one
  pipelined read of 15 hashes instead of one read per facility. Sent without waiting for the
  reply; a failure is logged and ignored.
- Each process keeps a local copy of the sums for the last `LOAD_WINDOW_MINUTES`, refreshed every
  5 seconds with jitter, in the background. The score reads only the local copy.
- A second counter, `spread:{minute}` with one field per (cell at resolution 7, severity,
  facility category), kept for a day, is written for a later city-spread view. Nothing reads it
  in this sprint.
- Evaluation scripts and unit tests run with load-aware routing off: their results must not
  depend on a random pick, and they must not write counters.
- `instance_id` is a random value chosen at process start.

### 7.4 Routes

- `POST /routes` keeps its contract. The web app sends only the recommended facility after a
  triage; it sends another candidate when the guest selects it; a mode change sends the facility
  currently shown. `ROUTES_UP_FRONT` (default 1, may be 3) is served through `/config` so the
  previous behaviour is one setting away.
- Each successful route stores (origin cell at resolution 9, facility, mode) → travel minutes in
  a bounded in-process cache with a 15-minute limit on entries.
- The request gains an optional `severity`, which the limiter in 7.5 uses.
- Sharing one upstream call between identical requests in flight was considered and left out:
  the web app already refuses a second request while one is loading.
- The Geoapify base URL becomes a setting (`GEOAPIFY_BASE_URL`), defaulting to the real one.

### 7.5 Geoapify budget

- A token bucket per process at `GEOAPIFY_RATE_PER_SECOND` (default 5, the free plan), one token
  per Geoapify call. Requests for an `emergent` or `urgent` triage are never refused by the
  limiter; they may push the bucket below zero, by at most one second of the rate. The severity
  comes from the client; the per-guest route limit bounds any abuse of that.
- When a request cannot have a token for each of its candidates, `/routes` answers with the candidate marked
  `estimated: true`, a travel time from 7.2 and no geometry. The web app shows the recommendation
  with the estimated time and "Route unavailable right now". `estimated` goes into
  `shared/types.ts` first.
- A counter `routes_degraded_total` records these answers.
- The limiter is per process. With R replicas the setting is the plan's rate divided by R; this
  is stated in the configuration notes, not solved in code.

## 8. Phase 4: harness and horizontal proof

### 8.1 Mock provider

- A small HTTP service under `backend/scripts/load/`: the Groq chat-completions endpoint and the
  Geoapify routing endpoint, with canned replies (a triage tool call, then a text reply; one
  route geometry) after a delay drawn from a configured distribution. Defaults reproduce Sprint
  21: LLM mean 2.2 s, routing p50 1.0 s and p95 1.9 s.
- Runs as a second service on staging for phase 5 and as a container in Compose.
- The API reaches it through `GROQ_BASE_URL` and `GEOAPIFY_BASE_URL`, set only on the staging
  Railway service.
- When either override is set, the API logs a warning at startup and `/health` reports
  `"stubbed": true`.

### 8.2 Load scripts

- Test B: steps of 40, 100, 250, 500, 1,000, 1,500 and 2,000 turns in flight (configurable, as in
  Sprint 21), conversations of two or three turns, origins drawn from a list spread over the
  city, busy answers counted apart from failures. Stop conditions as in Sprint 21: turn p95 over
  15 s or failures over 5%.
- Test A unchanged, plus `If-None-Match` on a share of requests so 304s are exercised.

### 8.3 Docker Compose

- A load balancer, N API replicas with fixed CPU and memory each, Postgres, Redis and the mock.
- Four checks, at 1, 2 and 4 replicas:
  1. Throughput at the bend of the latency curve grows with replicas.
  2. A conversation whose turns alternate replicas keeps its history.
  3. Load counters summed in Redis equal the recommendations made, with one field per replica.
  4. Stopping one replica mid-run leaves the others serving.
- Reported as a ratio between replica counts, not as capacity.
- No Prometheus in Compose: each replica's `/metrics` and the load tool's output are read
  directly.

## 9. Phase 5: measurement runbook

All runs target staging on the Sprint 21 box, never python-api.

1. **Calibration.** Real provider, then the mock, at 1, 2, 5, 10, 20 and 40 concurrent. Turn p50
   and p95 must agree within 10%; otherwise the mock's distribution is adjusted and this run is
   repeated.
2. **Chat breakpoint.** Mock, `MAX_TURNS_IN_FLIGHT=0`, steps to 2,000. Record the step at which
   p95 bends, what the box shows there (CPU, memory, pool, threads), and one profile.
3. **Admission.** Set `MAX_TURNS_IN_FLIGHT` to about 80% of the bend. Re-run the steps above it.
   Expected: latency flat, the excess refused with busy answers, no failures.
4. **Pool size.** From run 2, read connections in use and callers waiting. Set
   `DEMO_DB_POOL_MAX` to the peak in use plus 25%, at most the database's connection limit
   divided by the largest replica count planned. Re-run the step at the bend: no caller waits.
5. **Soak.** One hour at about 75% of the bend, mock provider. Pass: no failure, and resident
   memory in the last 30 minutes rises by less than 5%.
6. **Map path.** Test A to its new breakpoint, compared with 200 to 250 requests per second.
7. **Geoapify calls per 1,000 guests.** Counted at the mock, before (the `preview` build) and
   after.
8. **Larger box.** Only if run 2 bends below 1,000: repeat runs 2 and 3 at 2 vCPU / 2 GB and
   report them separately.

The report follows the Sprint 21 layout: environment, workload, one row per step, what gave way
first, the evidence for it.

## 10. Phase 6: close-out

1. `METRICS_BEARER_TOKEN`: generated locally with Python's `secrets`, set on python-api and
   staging without being printed, registered in Grafana Cloud with a scrape job. Dashboard steps
   are done with the owner logged in.
2. Move python-api and the demo Postgres to US East in a short window, with the wait-time worker
   repointed. Check first which path the Railway plan offers for the database (region migration
   or dump and restore). Afterwards: smoke suite, then calibration and one breakpoint step,
   reported next to the US West numbers.
3. Real-call test of the OpenAI client with `gpt-4o-mini`.
4. Doppler `stg`: `ANTHROPIC_MODEL` aligned with the code default.
5. Remove `VITE_GEOAPIFY_API_KEY` from Doppler and Vercel (owner).
6. PR to `preview`, smoke suite on the preview deployment.

## 11. Error handling

| Situation | Behaviour |
|---|---|
| Turn refused by admission | Busy answer with a short `retry_after`; nothing written; the client retries by itself |
| Provider quota error | Busy answer with 60 s, as today |
| Any other LLM failure | The "having trouble" reply with the 911 line, as today |
| History read fails | The turn fails with a 503 and is not sent to the LLM with an empty history |
| Wait-data reload fails | Previous copy kept; warning logged |
| `wait:last_run` absent | `max-age` is the floor; ETag uses the facility version alone |
| Load counter write or refresh fails | Ignored; the score uses the last local copy, or zero |
| No Geoapify token | Estimated answer, no geometry; emergent and urgent are never refused |
| Geoapify call fails | That candidate comes back with nulls, as today |
| Redis unreachable | Rate limiter allows the request, as today; the rest as in the rows above |

The history row is a deliberate change: answering without context is worse than refusing.

## 12. Out of scope

- The city-spread view (only its counters are written).
- A self-hosted routing engine and matrix-based ranking: the design for 1M daily users, described
  in the research file, not built.
- `LLM_PROVIDER_CHAIN` for guests.
- An async database layer.
- Moving Redis.
- Request batching windows.
- Caching drawn routes for reuse by other guests (Geoapify's terms on storing results are
  unchecked; the travel-time cache stores a number, not the route).

## 13. Testing

**Unit and API tests (phases 1 to 3)**

- Wait cache: reload after TTL, jitter within bounds, failed reload keeps the copy, one reload
  for concurrent callers.
- Bytes cache: one encode per version and filter set, 304 on a matching ETag without encoding,
  eviction at the size limit, `max-age` from `wait:last_run` including the floor and the absent
  key.
- Async clients: each provider against a fake async SDK, including Groq's single retry; fallback
  order and the "do not fall through" cases; instrumentation counters.
- Agent: the existing agent tests, made async, with unchanged expectations.
- History: a turn with no prior load of the session list sees earlier messages; the follow-up
  limit forces a classification at the configured turn; a failed history read gives 503.
- Admission: refusal at the limit, decrement on success and on exception, refused turn writes
  nothing and does not count against the rate limit.
- Cell index: same results as the scan on the real facility set and on random synthetic sets,
  including a guest far from any facility and severity filters that leave few candidates.
- Load-aware choice: urgent and emergent ignore load; the tie set and the random pick (with a
  seeded generator); missing wait data; counters unavailable.
- Counters: key shape, expiry, one field per instance, sum over the window.
- Limiter: refusal when empty, emergent and urgent always pass, degraded answer shape.
- Web app: waiting state, automatic retry and its limit, 911 line in busy and degraded states,
  one route requested up front, another on selection.

**Triage safety**

- The 27-vignette check on the default provider before phase 2 and after it: same result.

**Smoke**

- The four-scenario suite on staging after each of phases 1, 2 and 3, and on preview at the end.

## 14. Order of work

| Phase | Content | Executed by |
|---|---|---|
| 0 | Staging up, row cleanup, memory profile | Engineer, directly |
| 1 | Map path (section 5) | Plan, review batch 1 |
| 2 | Chat turn (section 6) | Plan, review batch 2 |
| 3 | Recommendation and routes (section 7) | Plan, review batch 3 |
| 4 | Mock, load scripts, Compose (section 8) | Engineer, directly |
| 5 | Measurement (section 9) | Engineer, with the owner |
| 6 | Close-out (section 10) | Engineer, with the owner |

Phase 0's memory result is read before phase 2 starts. Phase 4 can be built while phases 1 to 3
are in review.

## 15. Settings introduced

| Setting | Default | Where set |
|---|---|---|
| `WAIT_CACHE_TTL_SECONDS` | 30 | code default |
| `MAP_MIN_MAX_AGE_SECONDS` | 30 | code default |
| `LLM_MAX_CONNECTIONS` | 2000 | code default |
| `CHAT_HISTORY_MESSAGES` | 20 | code default |
| `MAX_TURNS_IN_FLIGHT` | 0 (no limit) | set after phase 5 |
| `ADMISSION_RETRY_SECONDS` | 3 | code default |
| `LOAD_AWARE_ROUTING` | on | code default |
| `LOAD_PENALTY_MINUTES` | per category | code default |
| `LOAD_SCORE_TIE_MINUTES` | 5 | code default |
| `LOAD_WINDOW_MINUTES` | 15 | code default |
| `ROUTES_UP_FRONT` | 1 | code default, served by `/config` |
| `GEOAPIFY_RATE_PER_SECOND` | 5 | per plan |
| `GEOAPIFY_BASE_URL`, `GROQ_BASE_URL` | real endpoints | override on staging only |
| `MEMORY_PROFILE` | off | staging only |

## 16. Design lenses used

- **release-it:** admission control as fail-fast instead of an unbounded queue; the Geoapify
  limiter and degraded answer as a bulkhead around the vendor; explicit connection limits;
  breakpoint, soak and stop-one-replica runs; every new behaviour reversible by a setting.
- **ddia-systems:** Postgres as the single system of record for conversations, with no second
  copy to disagree; the bytes cache and the cell index as derived data rebuilt from a version;
  atomic counters instead of locks; staleness of wait data made explicit through the last-run key.
- **system-design:** capacity stated from arithmetic before design (turns per second, LLM calls,
  vendor rate); stateless processes so replicas add capacity; two-stage lookup (coarse cell
  filter, then exact ranking).
- **clean-architecture:** the agent depends on `BaseLLMClient` only, so going async touches the
  interface and its implementations, not the triage rules; vendor URLs become settings at the
  edge; admission, wait cache, cell index and limiter are separate modules with one job each.
- **pragmatic-programmer:** the 15-minute interval and the data version each defined once;
  deletion of `cache_chat.py` rather than repair; the mock as a tracer through the real SDK path;
  estimates given as measured ranges with their conditions.
- **clean-code:** existing function signatures kept where behaviour is unchanged
  (`find_nearest_facilities`, `/routes`); the changed failure for an unreadable history is an
  explicit error, not an empty list.
