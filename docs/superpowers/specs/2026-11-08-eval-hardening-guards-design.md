# Spend cap, circuit breaker and narrow retry: design (Sprint 23, step 2)

Date: 2026-11-08. Settled with the owner in conversation the same day. Plan:
`docs/superpowers/plans/2026-11-08-eval-hardening-guards.md`.

Lenses used (which skill drove which decision is in the last section): clean-architecture,
pragmatic-programmer, clean-code, release-it.

## Why

Step 2 of Sprint 23 changes what the system answers, so it has to land before the paid pilot
(step 5) and the full run (step 6): the published under-triage numbers must come from the final
behaviour. Three guards, built as one stack so they are not built separately:

1. A **per-conversation spend cap**.
2. A **circuit breaker** per LLM provider.
3. A **narrow retry policy**: 429, 5xx and connection resets only, never a 400, never a timeout.

## Goals

- A guest in a long conversation still gets a triage result, not a refusal, once the conversation
  has spent its allowance.
- A provider that is failing is skipped fast; a provider that blips is retried once.
- The eval runs the same retry policy and the same cap as production, and the manifest records
  every setting that can change an answer, so a Doppler change between resumes cannot silently mix
  two configurations.
- One accounting point for tokens, so the later per-provider token budget does not count twice.

## Non-goals

- The per-provider tokens-per-minute bucket (`2026-10-14-llm-provider-budget.md`, Tasks 2 to 4).
  Still deferred; this design leaves the slot for it (see "Relation to the planned budget").
- Per-guest or daily caps. Layer 1 (guest + IP rate limit) already bounds how often one guest can
  start a turn.
- Any frontend change, any change to the `busy` response body, any new HTTP route.
- Money as a unit. Groq is on the free tier; tokens are what is scarce.

## Anti-goals (a failure even if it technically works)

- A conversation that stalls without a result because it hit our own cap. The cap must never turn
  into a refusal on a possible emergency.
- The system giving a severity or a facility without the model (no keyword triage in this step).
- Retrying a request that was wrong (400), which only repeats the cost.
- The eval silently reporting provider outages as clinical results.

## Decided by the owner

| # | Decision |
|---|---|
| D1 | **Cap reached:** the turn still classifies from what is known, returns a result and a short note. |
| D2 | **Every provider unavailable** (all breakers open, or the single provider is down): the guest gets a busy-style answer plus a fixed safety line (911 for an emergency, 211 for other help). No severity, no facility without the model. A keyword check that routes to an ER was offered and declined for now. |
| D3 | **The 400 retry is dropped.** `GroqClient` retried once on a 400 whose text contains `tool_use_failed`. It goes. Revisit only if the pilot shows it matters. |

## My calls (check these while reading)

| # | Call | Why |
|---|---|---|
| C1 | Unit is **tokens** (prompt + completion, as reported by the provider), scope is **one conversation** (the chat session id). | Free tier; tokens are the scarce unit; the session id is already the conversation key. |
| C2 | Counter in **Redis** (the Upstash instance used by `rate_limit.py`): `INCRBY` + 24 h expiry, **fails open** if Redis is unreachable. Eval uses an in-memory store. | State is out of process memory since Sprint 22; atomic increment is exact across replicas; a broken counter must not block care (same rule as `rate_limit.py`). |
| C3 | The cap is checked **before** the first model call of a turn. Reaching it makes the turn **forced-classify**, and the grounded reply is a **fixed template with no second model call**. The one forced call is never refused by the cap, so spend can pass the cap by at most one call per turn. | Forced classify already exists (`TRIAGE_MAX_FOLLOWUPS`) and bypasses the minimum-turn gate. A template removes the second call, so the cap really stops spend. |
| C4 | Default cap `30000` tokens (`LLM_CONVERSATION_TOKEN_CAP`). **A guess.** Step 5's pilot measures tokens per conversation and must check how often the cap bound; the value is fixed before step 6 and recorded in the manifest. | Roughly six turns at about 2.7k tokens (8,000 tokens a minute is about three turns on Groq). |
| C5 | After the cap, **every later turn** in that conversation is a forced classify (one call each). No hard ceiling above the cap. | Layer 1 limits a guest to about one turn a minute; a second ceiling is not worth its moving parts yet. Logged as a watch item. |
| C6 | Breaker: **per provider, in process, consecutive provider-side failures**. Opens after `LLM_BREAKER_FAILURES` (5), half-opens after `LLM_BREAKER_COOLDOWN_SECONDS` (30) and lets one probe through. | Replicas learn independently within five calls; a shared breaker is the future gateway's job. |
| C7 | What counts as a breaker failure: exactly `worth_trying_another_provider` (rate limit, timeout, 5xx, connection, 401/403). A 400 means the provider answered, so it resets the count. | One definition of "provider-side failure", already used by the fallback. |
| C8 | Retry: **2 attempts total** (`LLM_RETRY_ATTEMPTS`), full jitter, base 0.25 s, max 1 s. **Timeouts are not retried** even though the SDKs make `APITimeoutError` a kind of connection error. | The owner's list is 429, 5xx, connection resets; a 30 s timeout retried is another 30 s. |
| C9 | SDK retries are turned off (`max_retries=0`) in **every** mode, not only in chain mode. | Our policy must be the only one, or "never retry a 400" is not true and the eval differs from production. |
| C10 | **Stack order**, outermost first: `Fallback → Instrumented → Breaker → Retry → provider client`. | The breaker sees one failure per logical call, not one per attempt; an open breaker skips retries. |
| C11 | **Eval path** runs retry, cap and the template; the **breaker is off** (recorded as `breaker_enabled=false`). | Retry and cap change answers on healthy providers, so the eval must run with them. The breaker changes answers only during an outage; with it on, a five-minute Groq blip would turn many paid conversations into silent "unclassified". Off, a failed turn fails loudly and the checkpoint resume reruns it. The step 6 live-fallback leg uses the production chain, which has the breaker. |
| C12 | The "every provider unavailable" answer reuses the route's existing generic-failure branch (HTTP 200, saved assistant message, `turn_type: followup`, no severity), with the safety line added (911 and 211). It is **not** the 429 `busy` body. A real provider 429 that exhausts the chain keeps the existing `busy` response. | A `busy` body has no text field, so a safety line there needs a contract and frontend change (out of scope), and a saved message shows the line in the transcript. |
| C13 | The cap note and the safety line are fixed strings in code; their hash goes in the manifest. Wording is mine to edit. | Eval answers must be reproducible. |

## Design

### Layers (clean-architecture)

- **Port:** `BaseLLMClient` (unchanged). Retry, breaker and instrumentation are decorators behind it,
  so `LLMAgent` and the routes do not know they exist.
- **New port:** `SpendStore` (`total(conversation_id)`, `add(conversation_id, tokens)`), defined
  next to its user in `llm/spend.py`, with `InMemorySpendStore` (eval, tests) and `RedisSpendStore`
  (production). Redis is a detail.
- **Policy as pure functions:** `is_retryable(exc)`, `conversation_cap_reached(spent, cap)`,
  `capped_reply(severity, facility)`; breaker state machine takes an injected clock, retry takes an
  injected sleep and jitter. No test needs a network or a real wait.
- **Composition root:** `services/llm_agent.py` builds the stack (`build_guarded_client`), shared
  by the production factory and the eval adapter, so the two cannot drift.

### Cap flow in `LLMAgent.respond`

`respond` gains an optional `conversation_id`. `None` means no cap (callers that have no
conversation). Inside:

1. `spent = await store.total(id)` (fails open to 0); `capped = spent >= cap`.
2. `force = user_turns >= max_followups or capped`.
3. Every model call goes through one helper that adds `prompt + completion` tokens to the store
   after the call (the single accounting point).
4. If `capped` and the model returns a triage: severity, facility ranking and grounding checks run
   as today; the reply is `capped_reply(...)`, no second call.
5. If `capped` and the model does not return a triage: reply is the safety line, `turn_type:
   followup`, no severity.
6. The result dict gains `cap_reached: bool`. The route ignores it; the eval records it.

### Failure paths

| Situation | What happens |
|---|---|
| Groq 429/5xx/connection reset, once | Retried once after 0.25 s to 1 s jitter. |
| Groq fails 5 calls in a row | Breaker opens: Groq skipped in the chain; next provider answers. After 30 s one probe is allowed. |
| Chain mode, every breaker open | `ProviderCircuitOpen` (status 503) from the last provider; route returns the generic answer with the safety line (C12). |
| Single provider, breaker open | Same, immediately, with no 30 s hang. |
| Provider 400 | Not retried, not counted against the breaker, raised as today. In the eval, the conversation fails loudly. |
| Redis down | Cap and counting fail open; a warning is logged and counted. |

### Relation to the planned token budget

Two different resources: the **provider budget** protects a provider's rate limit (per provider,
per minute); the **conversation cap** protects our spend (per conversation, per session). They share:

- **Provider cooldown after a 429**: the breaker replaces it (a breaker opened by 429s is the same
  idea, with a half-open probe instead of a fixed wait). That part of the old plan is not built.
- **Token accounting**: one place (the agent's call helper) reads `usage`. A future
  `BudgetedLLMClient` wraps the same stack and reads `usage` from the response itself, so there is
  no second counter of the same tokens.
- **The tokens-per-minute bucket** stays deferred. Where it goes: a decorator between
  `Instrumented` and `Breaker`, raising a 429-like `ProviderBudgetExhausted` that the fallback
  already treats as "next provider". Nothing in this design blocks it.
- **Emergent priority** in the old plan only matters with the bucket; here the equivalent is built
  in (C3: the forced call is never refused).

### Eval manifest (`RunManifest`, `cli.py build_manifest`)

New fields, all enforced on resume: `retry_max_attempts`, `retry_base_delay_seconds`,
`conversation_token_cap`, `breaker_enabled`, `breaker_failure_threshold`,
`breaker_cooldown_seconds`, `capped_reply_sha256`. Constants and getters live beside the existing
ones in `services/llm_agent.py` / `config.py`. Consequence: a checkpoint written before this change
has no such fields and is refused on resume. That is intended (no paid results exist yet).

The transcript of each turn also stores `cap_reached`, so the pilot can say how often the cap bound.

### Observability (release-it)

Metrics: `llm_breaker_transitions_total{provider,to}`, `llm_retries_total{provider}`,
`llm_cap_reached_total`, `llm_spend_store_errors_total`. A breaker opening is expected output, not
an incident: alert only if it stays open (not part of this step; the metric makes it possible).

## Constraints

- Python 3.11, pydev venv, tests with `doppler run --`. No new dependency (`redis` already
  installed).
- Model names stay in env vars; none hard-coded.
- No change to `shared/types.ts` (no new route, no new response field the frontend reads).
- Severity values only `routine | moderate | urgent | emergent`.

## Left to the builder

File layout inside `backend/llm/`, exact metric help strings, the wording of log lines, the
backoff formula's exact shape (full jitter within the stated base and max).

## Open risks

- **Dropping the 400 retry** means a `tool_use_failed` glitch now fails the turn. In production it
  reaches the generic answer; in the eval it fails the conversation. The pilot must report how
  often this happens (D3 says revisit then).
- **Cap default is a guess** (C4); wrong in either direction changes measured numbers, which is why
  it is a manifest field and a pilot output.
- **Per-process breaker** on a multi-replica deploy behaves as five failures per replica.

## Which skill informed which decision

| Skill | Decisions |
|---|---|
| release-it | Breaker states and half-open probe (C6), retry with jitter and a small budget (C8), timeouts not retried (C8), stack order so retries do not amplify breaker counts (C10), fail open on the counter (C2), fail fast when open, metrics for transitions. |
| clean-architecture | Decorators behind `BaseLLMClient` (agent unchanged), `SpendStore` port with Redis as a detail, pure policy functions, one composition root shared by production and eval. |
| pragmatic-programmer | One definition of provider-side failure (C7, DRY), crash loudly in the eval (C11), one accounting point (DRY on tokens), reversibility: the budget slot stays open, tracer-bullet order in the plan. |
| clean-code | Small single-purpose modules, injected clock/sleep so tests do not wait, named constants for defaults, no flag arguments (separate classes for retry and breaker). |
