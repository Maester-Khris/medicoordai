# Guest Demo Sprint 2, Phase 2: performance tracking and measurement

Date: 2026-10-10 · Branch: `feat/demo-user-experience` · Sprint 21

Inputs: `CHANGELOG.md` (Sprint 21), `artifacts/2026-10-08-min-perf-tracking.md` (local, the
metric choices and the measurement protocol), the Phase 1 spec
(`2026-10-08-guest-demo-sprint2-phase1-design.md`), and the reads taken on 2026-10-09/10
(section 2).

## 1. Goal

Quote real numbers for the demo API: latency, throughput, error rate, the load at which it
degrades and what fails first, measured on a box sized on purpose, before any guest has the link.

Phase 2 has two parts with different owners:

- **Part A, code** (sections 4 to 9): instrumentation, configuration, a second LLM provider with
  fallback, removal of the broken Grafana push, load-test scripts, and one known fix. Written as an
  implementation plan.
- **Part B, measurement** (section 10): a runbook. It needs the Railway box, the admin tunnel and
  judgement about the numbers, so it is run by the engineer with the owner.

**Done when**

1. `/metrics` exposes latency histograms for the LLM call, routing and the graph lookup, an LLM
   outcome counter, LLM token counters and the database pool gauges.
2. Pool size and rate limits are set from environment variables, with today's values as defaults.
3. `LLM_PROVIDER_CHAIN` switches the chat path to an ordered fallback over Groq, OpenAI and
   Anthropic; unset, behaviour is exactly today's.
4. The Grafana push thread is gone and Grafana Cloud receives the API's metrics through a scrape
   job.
5. One report exists under `artifacts/perf/` with: environment, workload mix, one row per load
   step, the breakpoint of Test A and of Test B, what failed first, a profile pair that explains
   it, and Test B before and after the fix in section 9.
6. Web Vitals at the 75th percentile are compared with the published thresholds.

## 2. Evidence the design rests on

| Fact | Source |
|---|---|
| `python-api` runs `uvicorn main:app` with no `--workers`: one process, 13 threads, about 145 MB, capped at 0.5 vCPU and 500 MB | Railway SSH, 2026-10-10 |
| `medicoordai-staging` is deployed from `feat/eval-extension`, last deployed 2026-07-13 (no demo mode, no `/routes`) | Railway SSH and deployment list |
| Grafana Cloud Prometheus holds no API metric at all in 90 days; the push thread fails every 30 s with `'Response' object is not callable`; it also uses the Pushgateway method against a remote-write URL | Grafana query API through the owner's browser; Railway logs; `backend/observability.py` |
| Grafana Cloud's Metrics Endpoint integration scrapes a public URL every 60 s and requires Basic or Bearer authentication | Grafana documentation |
| `/metrics` is open to anyone when `METRICS_BEARER_TOKEN` is unset (`verify_metrics_token` only compares when the variable exists) | `backend/observability.py` |
| The chat handler (`routers/chat.py`, `async def send_message`) calls `agent.respond(...)` and `add_message(...)` directly. Both are blocking: the agent makes two LLM round trips. While one turn waits, the single process serves nothing else | Reading the code. **Not measured yet.** |
| Neither LLM client sets a timeout; they use the SDK defaults | `backend/llm/groq_client.py`, `anthropic_client.py` |
| The demo pool is `min_size=1, max_size=5, timeout=5` with a 5 s statement timeout | `backend/demo_db.py` |
| Phase 1 samples on preview: `POST /routes` mean 651 ms (15 calls); chat reply median 1.5 s, three of ten at about 10 s during a burst | `artifacts/perf/2026-10-10-0450-after-phase1.md` |
| Groq free tier: 30 requests and 8,000 tokens per minute, 200,000 tokens per day | Owner, 2026-10-08 |
| Sentry Web Vitals for `/` over 24 h, 25 page loads, mostly synthetic: LCP 619 ms, CLS 0.0008, TTFB 125 ms, INP not measured | Sentry dashboard, 2026-10-10 |
| `openai` 2.45, `groq` 1.0, `anthropic` 0.40 and `psycopg-pool` 3.3 are installed; Docker 29.5 is on the workstation; k6 and py-spy are not installed | `pip show`, `docker --version` |
| One chat turn costs about 1,900 tokens on the current Groq model (19,000 tokens over 10 single-turn conversations, 2 provider calls each, mean 3.3 s per call) | Local run of Test B against the plan's code, 2026-10-10 |
| With the chat code as it is, three concurrent turns took the turn p95 to 23 s locally and a `/metrics` read timed out while turns were in flight; with the fix in section 9, `/health` answered in 5 ms during a 1.6 s turn | Same local run. Small sample; the staging measurement is the real one |

## 3. Decisions

| # | Decision | Why |
|---|---|---|
| D1 | The load target is `medicoordai-staging`, resized to 1 vCPU and 1 GB with one worker for the test only, deployed from this branch, on the same demo database. | The public service keeps its size and bill. The test measures the real database and its real limits. No guest has the link. |
| D2 | One worker. No multi-process metrics. | The work is mostly waiting (LLM, Geoapify, database). One Python process cannot use more than about one core, so 1 vCPU is the useful size. Each uvicorn worker keeps its own counters, so several workers would make every scrape and every `/metrics` read inconsistent. Workers are added later only if the profile shows the CPU saturated by Python code. |
| D3 | Test data goes into the demo database. Load-test guests send the internal token so they are marked internal; the guest tables are truncated before the run if needed and cleaned after. | Owner's call, 2026-10-10. |
| D4 | k6 runs from the official container image. py-spy is installed inside the Railway container at test time. Nothing is installed on the workstation. | Owner's call. |
| D5 | Second provider: an OpenAI client plus an in-process ordered fallback, off by default. A deployed gateway is a later iteration. | Shows provider-agnostic resilience in metrics and traces without putting a new network hop inside what is being measured. Also answers Groq's free-tier limits for real guests. |
| D6 | Fallback is not enabled for guests until the triage vignette check has run on the fallback model. Load tests run one provider at a time. | A different model can classify severity differently. Mixed providers would make Test B's numbers unreadable. |
| D7 | Grafana: delete the push, let Grafana Cloud scrape `/metrics`. | No new dependency, no background thread that can fail silently (this one failed since Sprint 5). One sample per minute is enough for history and alerts; the load-test report reads k6 output and `/metrics` directly. |
| D8 | The chat blocking fix is written in this plan but applied after the first Test B. | Measure, explain with a profile, fix, measure again. |
| D9 | The LLM provider used for Test B is chosen when the test runs. | Owner's call; not a blocker. |

## 4. Instrumentation

All new metrics register on the existing `_registry` in `backend/observability.py`, so they
appear on `/metrics` with the route histograms.

One module, `backend/metrics.py`, owns the metric objects and a timing helper. It imports only
`prometheus_client` and the registry. The LLM, routing and graph code import it; it imports none
of them.

| Metric | Type | Labels | Recorded where |
|---|---|---|---|
| `llm_call_duration_seconds` | Histogram | `provider`, `outcome` | Around every provider call |
| `llm_calls_total` | Counter | `provider`, `outcome` | Same place |
| `llm_tokens_total` | Counter | `provider`, `kind` (`prompt`, `completion`) | From the usage the provider returns |
| `routing_call_duration_seconds` | Histogram | `mode`, `outcome` | Around the single Geoapify Routing call in `services/routing.py` |
| `graph_lookup_duration_seconds` | Histogram | `provider`, `outcome` | Around `get_symptom_graph_context` |
| `demo_db_pool_size`, `demo_db_pool_in_use`, `demo_db_pool_waiting` | Gauge | none | Read from `pool.get_stats()` at scrape time |

- `outcome` is one of `ok`, `rate_limited`, `timeout`, `error`. For routing it is `ok`, `no_route`,
  `timeout`, `error`. For the graph it is `ok` or `error`.
- `provider` for the LLM is `groq`, `openai` or `anthropic`. For the graph it is the configured
  provider name (the value of `GRAPH_RAG_PROVIDER`, lower-cased). With the provider off the lookup records near-zero
  durations; after Neo4j is back the same code records real ones.
- Histogram buckets, in seconds. LLM: 0.25, 0.5, 1, 2, 3, 5, 8, 13, 21, 34. Routing: 0.1, 0.25,
  0.5, 1, 2, 3, 5, 8. Graph: 0.005, 0.025, 0.1, 0.25, 0.5, 1, 2.5. They are chosen around the
  values already observed (LLM 1.5 to 10 s, routing 0.5 to 3 s) so percentiles interpolate inside
  populated buckets.
- No label carries a user, guest, session or message value. Label sets are fixed and small.

**LLM timing lives in one place.** A wrapper client, `InstrumentedLLMClient`, implements
`BaseLLMClient`, wraps one provider client and records the three LLM metrics. The factory returns
providers wrapped in it. Provider clients stay free of metric code.

**Outcome classification** is one function, `classify_llm_error(exc) -> str`, used by both the
instrumentation and the fallback: status code 429 is `rate_limited`; a timeout exception is
`timeout`; anything else is `error`. It reads `status_code` and the exception type name, which
the Groq, OpenAI and Anthropic SDKs all expose, so it imports none of them.

**`/metrics` guard.** `verify_metrics_token` returns 503 when `METRICS_BEARER_TOKEN` is unset, and
403 on a wrong or missing token. Today an unset variable leaves the endpoint open.

## 5. Configuration from environment variables

| Variable | Default | Read by |
|---|---|---|
| `DEMO_DB_POOL_MAX` | 5 | `demo_db.open_pool` |
| `DEMO_DB_POOL_TIMEOUT_SECONDS` | 5 | `demo_db.open_pool` |
| `RATE_LIMIT_CHAT_GUEST`, `RATE_LIMIT_CHAT_IP` | 10, 30 | `services/rate_limit.py` |
| `RATE_LIMIT_ROUTES_GUEST`, `RATE_LIMIT_ROUTES_IP` | 60, 180 | `services/rate_limit.py` |
| `LLM_TIMEOUT_SECONDS` | 30 | every provider client |
| `LLM_PROVIDER_CHAIN` | unset | `get_llm_client` |
| `OPENAI_API_KEY`, `OPENAI_MODEL` | none | `OpenAIClient` (the model has no default: the owner picks it) |

- Values are read through small functions at call time, as `config.py` already does, so tests can
  change the environment.
- An invalid or non-positive number falls back to the default and logs one warning; it never
  stops the API from starting.
- `DEMO_DB_POOL_MAX` is clamped to 1..50. The demo Postgres `max_connections` is read in the
  runbook and the default revisited from the load test.
- The rate-limit values are raised on staging only, for the test. Guests keep 10 and 30.

## 6. Second provider and fallback

**`OpenAIClient`** (`backend/llm/openai_client.py`) implements `BaseLLMClient` with the official
SDK's chat completions. It mirrors `GroqClient` (the two APIs have the same shape) without the
`tool_use_failed` retry, which is specific to Groq. It raises `RuntimeError` at construction when
`OPENAI_API_KEY` or `OPENAI_MODEL` is missing.

**`FallbackLLMClient`** (`backend/llm/fallback.py`) implements `BaseLLMClient` over an ordered list
of clients.

- A call goes to the first client. It moves to the next when the failure belongs to that
  provider: `rate_limited`, `timeout`, a 5xx status, a connection failure, or rejected credentials
  (401, 403: a revoked key must not take the chat down while another provider works). Each client
  is tried at most once per call. There is no retry loop and no sleep.
- Any other error (400, 404, 422, a parsing error) is raised immediately: it would fail on every
  provider, and switching would hide a bug.
- When every client has failed, the last exception is raised, so the chat router's existing
  handling (429 becomes the "busy" response) still applies.
- Each switch logs one line, `llm_fallback`, with the provider left, the provider tried next and
  the outcome. `model_name` reports the client that answered last.
- No state is kept between calls: every call starts from the first provider. A circuit breaker
  that remembers a failing provider is a later step, taken if the metrics show repeated wasted
  attempts.

**Factory** (`get_llm_client`):

- `LLM_PROVIDER_CHAIN` unset or empty: today's behaviour, one client chosen by `LLM_PROVIDER`.
- `LLM_PROVIDER_CHAIN=groq,openai,anthropic`: a `FallbackLLMClient` over those providers in that
  order. An unknown name, or a provider whose key is missing, is skipped with one warning; if
  nothing is left the factory raises.
- In both cases every provider client is wrapped in `InstrumentedLLMClient`, so a failed first
  attempt and the successful second one are both visible, each under its own provider label.

**Timeouts and retries.** Each client passes `LLM_TIMEOUT_SECONDS` to its SDK. Inside a chain the
SDK's own retries are set to zero, so the next provider is the only retry layer. With no chain the
SDK keeps its default retries: turning them off there would surface more "busy" answers to guests
than today.

## 7. Grafana

- Delete from `backend/observability.py`: the push thread, the `push_to_gateway` import, and the
  reads of `GRAFANA_PROMETHEUS_REMOTE_WRITE_URL`, `GRAFANA_PROMETHEUS_INSTANCE_ID` and
  `GRAFANA_API_TOKEN` for metrics. The Loki log variables are not touched.
- After deploy the owner creates one Metrics Endpoint scrape job per service in Grafana Cloud
  (URL `https://<service>/metrics`, Bearer, the value of `METRICS_BEARER_TOKEN`), through the
  `browser-read-control` skill. It is the last step of the runbook.
- The three existing alerts ("Service down", "Error rate > 5%", "p95 latency > 2s") are checked
  once data arrives. Rewriting them is out of scope unless they do not evaluate.

## 8. Load-test scripts

Under `backend/scripts/load/`, run with the official k6 image; nothing is installed on the host.

```
docker run --rm -i --network host \
  -e BASE_URL=... -e INTERNAL_TOKEN=... -e SCENARIO=breakpoint \
  -v "$PWD/backend/scripts/load:/scripts" -v "$PWD/artifacts/perf:/out" \
  grafana/k6 run /scripts/test_a.js --summary-export /out/<file>.json
```

| File | Content |
|---|---|
| `lib.js` | Base URL, headers (`X-Guest-Id` per virtual user, `X-Internal`), thresholds, random Toronto coordinates |
| `test_a.js` | Non-LLM mix. `SCENARIO` selects `smoke` (2 requests per second, 1 min), `average` (ramp, hold 5 min), `breakpoint` (arrival rate 10, 25, 50, 100, 150, 200 per second, 2 min each), `soak` (average rate for 1 hour) |
| `test_b.js` | Chat. Concurrent turns 1, 2, 5, 10, 20, 40, each held 2 min. One virtual user is one fresh guest: create a session, send one symptom message, read the reply |
| `scenarios.json` | The twelve single-turn symptom messages with coordinates, copied from `scripts/triage_deepeval/symptom_scenarios.py` |

- **Test A runs two streams.** The mix: `GET /facilities` 42%, `GET /facilities/nearby` 32% (random
  point, radius and category), `GET /config` 16%, `GET /health` 10%. Beside it, `POST /routes`
  (random mode among car, bike, walk) at a fixed low rate that never ramps: 0.2 per second in
  smoke, 1 in average, 2 in breakpoint, 0.5 in soak. Each `/routes` request makes three Geoapify
  calls on a metered key. Transit is excluded from load for the same reason and because it is the
  slowest. Random points stay north of the shoreline: a point in the lake makes Geoapify answer
  400.
- **Arrival rate, not looping users,** for the breakpoint: a slow server must not slow the
  generator down and hide the tail.
- **Thresholds**, ours and stated as assumptions: Test A error rate under 1%, p95 under 500 ms,
  p99 under 1 s. Test B error and "busy" rate under 5%, turn p95 under 15 s. A scenario stops when
  a threshold has failed for a full step.
- **Test B counts 429 and "busy" on their own line.** Once they appear the test is measuring the
  provider's rate limit, not this API.
- The scripts print nothing secret, and the token comes from the environment.

## 9. The chat blocking fix

In `routers/chat.py`:

- `send_message`: `agent.respond(...)` and both `add_message(...)` calls run through
  `run_in_threadpool`.
- `create_new_session`: `create_session(...)` the same way. `generate_session_title` is a pure
  string function and stays where it is.

Behaviour, responses and error handling do not change. It is one commit, the last of the plan,
so the commit before it can be pushed as its own branch and deployed to staging for the first
Test B (section 10).

Consequence to watch in the second Test B: concurrent turns now hold thread-pool threads (40 by
default) and database connections at the same time, so the pool size in section 5 becomes the
next limit. That is expected and is what the pool gauges are for.

## 10. Runbook (Part B)

Run after Part A is reviewed and merged to the branch. Each step names who acts.

1. **Staging box (owner).** Resize `medicoordai-staging` to 1 vCPU and 1 GB. Point it at
   the branch `perf/before-chat-fix`, which the engineer pushes at the commit just before the fix in
   section 9 (Railway deploys a branch head, so the "before" code needs its own branch). Start
   command unchanged
   (one worker). Set `DEMO_MODE=true`, `POSTGRES_DB_URL_APP`, `GEOAPIFY_API_KEY`,
   `METRICS_BEARER_TOKEN`, `DEMO_INTERNAL_TOKEN`, `GRAPH_RAG_PROVIDER=off`,
   `ROUTING_SHADOW_SAMPLE_RATE=0` (the shadow comparison adds a Geoapify call to a share of chat
   turns), the raised rate limits, and the LLM provider chosen for Test B.
2. **Database (engineer, owner's go-ahead).** Through the admin tunnel: read `max_connections`;
   enable `pg_stat_statements` (`shared_preload_libraries`, restart, `create extension`); truncate
   the guest tables if a clean start is wanted.
3. **Snapshot (engineer).** `baseline --label phase2-start` against staging.
4. **Test A (engineer).** Smoke, average, breakpoint. Record per step: achieved rate, error rate,
   p50, p95, p99, CPU and memory from the Railway service page, connections from
   `pg_stat_activity`, and the pool gauges.
5. **Profile (engineer).** `railway ssh`, install py-spy, `py-spy dump` to see whether attaching is
   allowed. If it is: one 60 s `py-spy record --idle` at the lowest step and one at the
   breakpoint. If not: set a Sentry profiles sample rate on staging and repeat the two steps.
6. **Test B, before (engineer).** Concurrency ramp, with a profile at 1 and at the breaking level.
7. **Fix (owner deploys).** Point staging at `feat/demo-user-experience`, whose head carries the
   fix. Run Test B again, same ramp. `perf/before-chat-fix` is deleted in the cleanup step.
8. **Soak (engineer).** Test A at the average rate for one hour, memory logged every 30 s. No LLM
   traffic.
9. **Fallback check (engineer).** With `LLM_PROVIDER_CHAIN` set and the first provider forced to
   fail (an invalid key on staging), send three chat turns: expect an answer, an `llm_fallback`
   log line and both providers in `llm_calls_total`.
10. **Web Vitals (engineer, owner's browser).** Read the 75th percentiles and compare with LCP 2.5 s,
    INP 200 ms, CLS 0.1, TTFB 0.8 s.
11. **Report (engineer).** `artifacts/perf/<date>-phase2-report.md`, with the content listed in
    section 1. Every number carries the box size beside it.
12. **Grafana (owner's browser, engineer driving).** Create the scrape jobs; confirm
    `http_requests_total` arrives; check the three alerts.
13. **Cleanup (engineer, owner's go-ahead).** Delete the internal guests created by the tests.
    Owner returns staging to its usual size and removes the raised limits.
14. **Latency fix beyond section 9:** only if the report shows another single dominant cost. It
    gets its own short design.

Run by hand because: steps 1, 7 and 13 change paid infrastructure; step 2 restarts a database;
steps 4 to 9 need the numbers read and the next step chosen from them.

## 11. Error handling

| Failure | Behaviour |
|---|---|
| A metric cannot be recorded | Never fails the request: the timing helper records in a `finally` and swallows nothing from the wrapped call |
| `pool.get_stats()` fails at scrape time | The three gauges report 0 and one warning is logged; `/metrics` still answers |
| Invalid environment number | Default used, one warning |
| Provider in the chain has no key | Skipped with one warning at construction; the chain continues |
| Every provider fails | Last exception raised; the router's existing handling applies |
| `METRICS_BEARER_TOKEN` unset | `/metrics` answers 503 |

## 12. Out of scope

- A deployed LLM gateway (OmniRoute, LiteLLM): the next iteration after the in-process fallback.
- Several workers and Prometheus multi-process mode.
- GraphRAG reintegration and the Neo4j instance.
- Enabling fallback for guests (waits for the vignette check).
- A circuit breaker or provider health memory in the fallback.
- Streaming responses and time to first token.
- Cost tracking.

## 13. Testing

**Backend (pytest, no network)**

- `metrics`: the timing helper records one observation and one count per call, with the outcome
  label for success, rate limit, timeout and error; it re-raises the wrapped exception unchanged.
- `classify_llm_error`: 429, timeout exceptions by type name, 5xx, other 4xx, plain exceptions.
- `InstrumentedLLMClient`: tokens counted from the response usage; a failing call is counted and
  re-raised; the wrapped client receives the arguments unchanged.
- `OpenAIClient`: request shape (messages, tools, forced tool choice, stop), response mapping
  including tool calls, missing key or model at construction. The SDK client is replaced by a
  fake.
- `FallbackLLMClient`: first provider answers; switch on 429, on timeout, on 503; no switch on
  400; all fail raises the last error; each provider called at most once; the log line.
- Factory: chain unset keeps today's client type; chain order respected; unknown name and missing
  key skipped; empty result raises.
- Routing and graph: one histogram observation per call with the right labels, including the
  failure paths. Existing tests keep passing unchanged.
- Pool gauges: values come from `get_stats()`; a failing `get_stats()` yields zeros.
- Configuration readers: default, valid override, invalid value, clamp.
- `/metrics`: 503 without a configured token, 403 with a wrong one, 200 with the right one.
- Observability: no thread is started by `init_metrics`.
- Chat router after the fix: the agent and the message writes are called through the thread pool
  (the handler no longer calls them on the event loop), and every existing chat test passes.

**Load scripts:** `k6 inspect` on both files inside the container (parses the script and options
without sending a request), and the smoke scenario against a local stack.

**Every change in the plan was written, tested and replayed before it was landed.** Phase 1's three
plan defects all came from untested plan code. For this phase the code was built in a scratch
checkout, split into one test patch and one code patch per task, and replayed in order on a clean
checkout: tests failing first, passing after the code, 639 backend tests green at the end, and a
final tree identical to the verified one. Both k6 scripts were run against a local server.

## 14. Order of work

Three parts, twelve commits, detailed in the plan:

1. Metrics module, routing, graph and pool instrumentation, configuration variables, `/metrics`
   guard, removal of the Grafana push.
2. Error classification, instrumented client, OpenAI client, fallback, factory, timeouts.
3. k6 scripts, documentation, and the chat fix as the final separate commit.

## 15. Design lenses used

| Skill | Where it shaped the design |
|---|---|
| release-it | Timeouts on every provider call, one retry layer (the fallback), no retry storm, bounded pool with an exported wait count, test past the breaking point, soak for leaks, measure before fixing (sections 5, 6, 8, 10). |
| clean-architecture | `metrics.py` depends on nothing in the application; timing and fallback are wrappers around the provider interface, so provider clients and the agent do not change (sections 4, 6). |
| pragmatic-programmer | One error classifier shared by metrics and fallback; one timing helper for three call sites; the gateway deferred until the wrapper has shown what it needs (sections 4, 6, 12). |
| clean-code | Small single-purpose units (`classify_llm_error`, `InstrumentedLLMClient`, `FallbackLLMClient`); configuration read through named functions (sections 4 to 6). |
| supabase-postgres-best-practices | Pool sized against `max_connections`, connection use observed during load, `pg_stat_statements` for the slowest statements (sections 5, 10). |
| test-driven-development | Every unit in section 13 is written test-first in the plan, and the plan's changes were replayed on a clean checkout before they were landed. |
