# Emergent routing to ERs, and a token budget per LLM provider: design

Date: 2026-10-14. Settled with the owner in conversation the same day. Two independent pieces,
one plan each:

- `docs/superpowers/plans/2026-10-14-emergent-er-only.md`
- `docs/superpowers/plans/2026-10-14-llm-provider-budget.md`

Lenses used: clean-architecture (the budget is a wrapper behind the existing `BaseLLMClient`
port, so the agent and the routes do not change shape), pragmatic-programmer (one authoritative
ER list read by the loader and by the one-time update: DRY on knowledge; crash early on a missing
list), clean-code (pure functions for the rules, named constants), release-it (fail fast, a
cooldown breaker on a provider's 429, priority traffic never shed).

## Part 1: emergent cases go only to facilities with an emergency department

### Problem

The original import (`seed/run.py`, `SEVERITY_MAP`) gives every facility of category `hospital`
the severities `emergent, urgent, moderate, routine`. The Ontario source labels many places
"hospital" that have no emergency department: rehabilitation centres, a hospice, CAMH sites, a
surgical unit, a cosmetic surgery institute. Emergent cases are routed strictly to the nearest
facility that accepts `emergent` (`services/recommendation.py`), so whichever of these is nearest
wins. On a 1,170-point grid over Toronto (local data, 2026-10-14), 16% of points send an
emergent case to a facility that is plainly not an ER. The chest-pain case at (43.70, −79.40) is
sent to Toronto Rehabilitation Institute, Hillcrest Centre.

### Rule

A facility accepts `emergent` only if it is on a reviewed list of facilities with an emergency
department, `backend/scripts/demo_seed/emergency_departments.json`. Every other `hospital` row
gets `urgent, moderate, routine`. `ambulatory` and `residential` rows keep their source values.
`category` is not changed.

### How the list is built

From the wait-time scraper's own matching (`workers/scraper.py`), run read-only against the local
copy of the facilities:

1. Facilities matched to an ERstat or HowLongWillIWait entry are ERs by evidence. They go on the
   list.
2. Scraped names in the Toronto area that did not match are reviewed with the owner: an ER we hold
   under another name is added (and gets an alias in `workers/hospital_aliases.json` in a later
   change, not here); an ER we do not hold is noted and skipped.
3. Each entry records its evidence. The scraper never grants `emergent` by itself: a wrong name
   match would then send emergencies to the wrong place.

### What can and cannot undo it

- The wait-time worker cannot: it reads `id, name` of `category = 'hospital'` rows and writes only
  `wait_times`.
- A re-seed could: `seed_facilities.py load` upserts `accepted_severity` from the Supabase
  export, which still carries the old rule. The rule therefore goes into the loader. The legacy
  Supabase rows stay as they are (out of scope).
- The API keeps the facility list in memory from startup with no expiry (`cache.py`), so the fix
  is live only after `python-api` restarts.

### Accepted trade-off

An ER missing from the list sends emergent cases to the next ER further away. That is a far safer
failure than a rehabilitation centre.

### Verification

Database (list of emergent facilities), the grid check (16% to 0%), `GET /facilities?severity=emergent`
on the public API, and one real chat turn at the chest-pain point.

## Part 2: a token budget per LLM provider (layer 4)

### Problem

`python-api` runs Groq alone (`LLM_PROVIDER_CHAIN` unset). The free tier allows about 8,000 tokens a
minute (about 3 turns) and 200,000 a day (about 80 turns), per organisation. Past either, Groq
answers 429 and the guest gets the busy answer until the limit resets. The fallback chain exists in
the code (`llm/fallback.py`) and already switches on a 429, but it is off, and when on it only
reacts after a refused call.

### Layers (the full picture; this part builds layer 4 only)

| Layer | Exists | Key | Past the limit | Emergent |
|---|---|---|---|---|
| L1 requests | yes | guest + IP, fixed window | busy | not exempt (see watch item) |
| L2 concurrency | yes | process, `MAX_TURNS_IN_FLIGHT` | fast busy | not exempt (see watch item) |
| L3 tokens per user | no, deferred | guest | busy | exempt |
| L4 provider budget | built here | provider, per process | next provider in the chain | exempt |

### Design of layer 4

- `BudgetedLLMClient` wraps one provider client and holds a token bucket sized at 90% of that
  provider's tokens-per-minute limit (`LLM_TPM_<PROVIDER>`, e.g. `LLM_TPM_GROQ=8000`), refilled
  continuously. Providers without the setting are not wrapped.
- Before a call it takes an estimate (message and tool text / 4, plus a completion allowance).
  After the call it corrects the bucket with the real usage. A failed call gives the estimate back.
- When the bucket cannot cover the estimate it raises `ProviderBudgetExhausted` (status 429).
  `FallbackLLMClient` already treats a 429 as the provider's failure and moves to the next provider,
  so the switch happens before the provider ever refuses. If no provider is left, the existing 429
  handler in the chat route gives the busy answer.
- When the provider itself answers 429, the wrapper stops sending to it until its `Retry-After`
  (60 s when absent). This covers the daily cap without a daily counter: a daily refusal carries a
  long `Retry-After`, and a restart only costs one more refused call.
- Emergent: the call that writes the answer for an emergent triage runs in a priority context.
  Priority calls are never refused by the budget; they may take the bucket into debt down to minus
  its capacity, which ordinary calls pay back as it refills (the Geoapify limiter's rule).
  A provider's own cooldown still applies to them, since that provider is refusing anyway; the last
  provider of the chain (Anthropic) has no budget, so an emergent call always has a provider.
- In process, no Redis: the demo runs one process, so a per-process bucket is exact, adds no network
  call to a turn, and costs no Upstash commands. Several processes set `LLM_TPM_*` to their share,
  as `GEOAPIFY_RATE_PER_SECOND` already does. The shared counter belongs to the LiteLLM gateway
  (next sprint).

### Changes from what was discussed

- No daily counter: the cooldown on the provider's own 429 replaces it (fewer moving parts, same
  effect, reactive fallback still the safety net).
- No Redis: see above.
- Defaults taken where no answer was given: no in-memory wait before switching (a provider is
  always available, so waiting buys nothing), and no "same provider for the whole conversation"
  (it needs conversation state; logged as a watch item).

### Deferred and watch items (recorded in `CHANGELOG.md`)

- L3, tokens per user: not on the demo (L1 already caps a guest at about one turn a minute).
  Required before a production launch, where a long conversation costs more per turn.
- Emergent bypass of L1 and L2: dropped for now (severity is only known after the LLM call, so it
  needs a pre-check and a reserved slice). Watch during the demo: busy answers on turns that later
  come back emergent.
- Provider switching mid-conversation: watch for tone or behaviour changes when a conversation
  moves from Groq to Anthropic.
- Configuration: `LLM_PROVIDER_CHAIN=groq,anthropic` and `LLM_TPM_GROQ=8000` in Doppler `stg`
  (python-api) and on staging; `ANTHROPIC_MODEL=claude-haiku-4-5` stays pinned on both
  (both 4-5 and 5-5 passed a plain and a forced-tool call on 2026-10-14).

## Sources

- Stripe, "Scaling your API with rate limiters": https://stripe.com/blog/rate-limiters
- Envoy AI Gateway, usage-based rate limiting: https://aigateway.envoyproxy.io/docs/capabilities/usage-based-ratelimiting
- LiteLLM routing (per-deployment TPM, usage-based routing): https://docs.litellm.ai/docs/routing
- Groq rate limits: https://console.groq.com/docs/rate-limits
