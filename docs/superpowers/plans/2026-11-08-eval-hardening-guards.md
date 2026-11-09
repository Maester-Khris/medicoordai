# Spend Cap, Circuit Breaker and Narrow Retry: Implementation Plan

> **For agentic workers:** Tests come first and are written by Claude. Tasks 2, 3 and 4 (leaf modules,
> code still to be written) are delegated to Gemini through `claude-agy-orch` on a throwaway branch;
> Claude reviews every diff (max 3 review batches). Tasks 1, 5, 6, 7 and 8 touch the agent, the
> route, the eval and the manifest, where one wrong line changes measured numbers: Claude does them.
> Steps use checkbox (`- [ ]`) syntax.

**Goal:** A conversation that reaches its token allowance still gets a result; a failing provider is
skipped fast; transient provider errors are retried once and 400s never; the eval runs the same
retry policy and cap as production, with every answer-affecting setting in the run manifest.

**Architecture:** Decorators behind `BaseLLMClient` (`Retry`, `Breaker`) built into one stack by a
single function shared by production and the eval; a `SpendStore` port (Redis in production,
in-memory in the eval) read and written at one point in `LLMAgent`.

**Tech Stack:** Python 3.11, FastAPI, asyncio, redis (already installed), prometheus-client, pytest.

**Spec:** `docs/superpowers/specs/2026-11-08-eval-hardening-guards-design.md` (decisions D1-D3, calls C1-C13).

## Global Constraints

- Work only in the worktree `/home/niki/Documents/saas/medicoordai-step2`, branch `feat/eval-hardening-step2` (cut from `feat/eval-hardening`). No push, no merge, no commit to `main` or `preview`.
- `source /home/niki/Documents/workenv/pydev/bin/activate` first; tests with `cd backend && doppler run -- pytest <path>`. No new venv, no new dependency.
- Settings read through functions in `backend/config.py` using `env_int` (a bad value falls back with one warning). New settings: `LLM_RETRY_ATTEMPTS` (2), `LLM_BREAKER_FAILURES` (5), `LLM_BREAKER_COOLDOWN_SECONDS` (30), `LLM_CONVERSATION_TOKEN_CAP` (30000). Retry delays are constants (base 0.25 s, max 1.0 s).
- No model name hard-coded. Severity values only `routine | moderate | urgent | emergent`.
- Commits: conventional, one line, no body, no co-author, no AI attribution; staged by name in one `git add` per task; **shown to the owner and approved before each commit**.
- After code changes: `graphify update .`.
- Do not touch `*.local.md`.
- The worktree has no Doppler scope: use `doppler run --project medicoord --config dev_personal --` in place of bare `doppler run --`.

## Review Focus

- `is_retryable` must be false for timeouts even though SDK `APITimeoutError` subclasses `APIConnectionError` (test in Task 2).
- A 400 resets the breaker's failure count and is never retried (Tasks 2, 3).
- Half-open lets exactly one probe through; concurrent callers during the probe are refused (Task 3).
- `RedisSpendStore` failure never raises into the agent (Task 4).
- The capped path makes exactly one model call (the forced classify), no second call (Task 5).
- Every new field is in `RunManifest`, `build_manifest`, and covered by a resume-mismatch test (Task 7).
- Existing single-provider behaviour changes by design: SDK retries are now off everywhere (Task 6). Check no test or caller relied on `max_retries=None`.

---

### Task 1: Branch hygiene and baseline

**Files:** none.

- [ ] **Step 1:** In the worktree, run `cd backend && doppler run -- pytest tests/llm tests/scripts -q` and record the pass count as the baseline.
- [ ] **Step 2:** Confirm `git status` is clean and the branch is `feat/eval-hardening-step2`.

Expected: all green (the step 1 suite). Any failure here is reported, not fixed in this plan.

### Task 2: Retry policy (Gemini)

**Files:**
- Create: `backend/llm/retry.py`
- Test: `backend/tests/llm/test_retry.py`
- Modify: `backend/config.py` (add `llm_retry_attempts()`), `backend/metrics.py` (add `LLM_RETRIES` counter `llm_retries_total{provider}`)

**Interfaces:**
- Produces: `is_retryable(exc: BaseException) -> bool`; `RetryingLLMClient(inner: BaseLLMClient, provider: str, attempts: int, base_delay: float = 0.25, max_delay: float = 1.0, sleep: Callable[[float], Awaitable[None]] = asyncio.sleep, jitter: Callable[[], float] = random.random)`.
- Consumes: `llm.base.BaseLLMClient`; `llm.instrumented.classify_llm_error` (to exclude timeouts).

- [ ] **Step 1: Write the failing tests (Claude)** in `backend/tests/llm/test_retry.py`. Use fakes like `tests/llm/test_fallback.py` (`_StatusError`, an `APITimeoutError` and an `APIConnectionError` class defined in the test, the latter with the timeout class as a subclass of it, mirroring the SDKs). Cases:
  - `is_retryable`: 429 true; 500, 502, 503 true; 400, 401, 403, 404 false; `ConnectionError` true; `APIConnectionError` true; `APITimeoutError` (subclass of `APIConnectionError`) **false**; plain `ValueError` false.
  - Transient then success: fake raises 503 once, then answers; client returns the answer, `calls == 2`, the injected `sleep` was awaited once with a value in `(0, max_delay]`.
  - Attempts exhausted: `attempts=2`, fake always 503; raises the last error, `calls == 2`.
  - 400 not retried: `calls == 1`, raises, `sleep` never awaited.
  - Timeout not retried: `calls == 1`.
  - `attempts=1` means no retry.
  - Delay bound: with `jitter=lambda: 1.0` and `base_delay=0.25`, first sleep equals 0.25; with attempts large, no sleep exceeds `max_delay`.
  - Metric: `LLM_RETRIES` for the provider increases by one per retry.
- [ ] **Step 2:** Run `doppler run -- pytest tests/llm/test_retry.py -q`. Expected: fail (module missing).
- [ ] **Step 3: Implement (Gemini).** `is_retryable`: false if `classify_llm_error(exc) == "timeout"`; true if `status_code == 429` or an int `>= 500`; true if `ConnectionError` or any class name in the MRO contains `"Connection"`; else false. `RetryingLLMClient.chat` loops `attempts` times; between attempts sleeps `jitter() * min(max_delay, base_delay * 2**attempt_index)`; raises the last exception; increments `LLM_RETRIES` per retry; forwards `model_name`.
- [ ] **Step 4:** Tests pass. Then `doppler run -- pytest tests/llm -q` still green.
- [ ] **Step 5:** Commit (after owner approval): `feat(llm): add a narrow retry policy for 429, 5xx and connection errors`

### Task 3: Circuit breaker (Gemini)

**Files:**
- Create: `backend/llm/breaker.py`
- Test: `backend/tests/llm/test_breaker.py`
- Modify: `backend/config.py` (`llm_breaker_failures()`, `llm_breaker_cooldown_seconds()`), `backend/metrics.py` (`LLM_BREAKER_TRANSITIONS` counter `llm_breaker_transitions_total{provider,to}`)

**Interfaces:**
- Produces: `ProviderCircuitOpen(provider: str)` with `status_code = 503`; `CircuitBreakerLLMClient(inner: BaseLLMClient, provider: str, failure_threshold: int, cooldown_seconds: float, clock: Callable[[], float] = time.monotonic)`; property `state -> str` (`"closed" | "open" | "half_open"`).
- Consumes: `llm.instrumented.worth_trying_another_provider`.

- [ ] **Step 1: Write the failing tests (Claude)** with a manual clock (`list` cell) and a scripted fake. Cases:
  - Closed stays closed below the threshold; a success resets the consecutive count.
  - `failure_threshold` consecutive provider-side failures (503, 429, timeout, connection) open it; the next call raises `ProviderCircuitOpen` **without calling the inner client** (`calls` unchanged).
  - A 400 neither counts nor opens: after four 503s, a 400, then one 503, the breaker is still closed (the 400 reset the count).
  - After `cooldown_seconds` the next call is a probe: success closes it; failure reopens it for another full cooldown.
  - Half-open admits exactly one probe: while a probe is awaiting (use an `asyncio.Event` in the fake), a second concurrent call raises `ProviderCircuitOpen`.
  - `ProviderCircuitOpen.status_code == 503` and `worth_trying_another_provider(ProviderCircuitOpen("groq"))` is true (so the fallback moves on).
  - Transitions counted: `llm_breaker_transitions_total{provider,to}` for `open`, `half_open`, `closed`.
- [ ] **Step 2:** Run; expected fail.
- [ ] **Step 3: Implement (Gemini).** State machine as described in spec C6/C7. Single `asyncio`-safe probe flag (no locks needed: the check-and-set happens before any `await`).
- [ ] **Step 4:** Tests pass; `tests/llm` green.
- [ ] **Step 5:** Commit (after approval): `feat(llm): add a per-provider circuit breaker`

### Task 4: Spend store (Gemini)

**Files:**
- Create: `backend/llm/spend.py`
- Test: `backend/tests/llm/test_spend.py`
- Modify: `backend/config.py` (`llm_conversation_token_cap()`), `backend/metrics.py` (`LLM_SPEND_STORE_ERRORS` counter, `LLM_CAP_REACHED` counter)

**Interfaces:**
- Produces: `SpendStore` (Protocol) with `async total(conversation_id: str) -> int` and `async add(conversation_id: str, tokens: int) -> None`; `InMemorySpendStore()`; `RedisSpendStore(client, ttl_seconds: int = 86400)`; `conversation_cap_reached(spent: int, cap: int) -> bool` (`spent >= cap`).
- Consumes: `redis` client object passed in (the app passes `services.wait_times.redis_client`); calls run through `starlette.concurrency.run_in_threadpool` because the client is synchronous.

- [ ] **Step 1: Write the failing tests (Claude).** Cases:
  - `InMemorySpendStore`: `total` of an unknown id is 0; `add` accumulates per id; ids are independent.
  - `RedisSpendStore` against a fake client implementing `incrby`, `expire`, `get` (and `pipeline` if used): `add` increments by `tokens` and sets the expiry; `total` returns an int; a missing key is 0.
  - **Fails open:** a fake client whose methods raise `ConnectionError`: `total` returns 0, `add` returns without raising, and `LLM_SPEND_STORE_ERRORS` increases.
  - `conversation_cap_reached(29999, 30000)` is false; `(30000, 30000)` and above true.
  - Key format is `llm_spend:<conversation_id>` (asserted on the fake).
- [ ] **Step 2:** Run; expected fail.
- [ ] **Step 3: Implement (Gemini).** Redis `INCRBY` then `EXPIRE` (one pipeline round trip); `add` ignores `tokens <= 0`.
- [ ] **Step 4:** Tests pass.
- [ ] **Step 5:** Commit (after approval): `feat(llm): add a per-conversation token spend store with a Redis implementation`

### Task 5: The agent enforces the cap (Claude)

**Files:**
- Modify: `backend/services/llm_agent.py`
- Test: `backend/tests/llm/test_agent_cap.py` (new)

**Interfaces:**
- Produces: `LLMAgent(client, graph_provider, spend_store: SpendStore | None = None)`; `respond(..., conversation_id: str | None = None)`; result dict gains `"cap_reached": bool`; module constants `CAPPED_NOTE`, `SAFETY_LINE = "If this is an emergency, call 911. For other health help, call 211."`; pure `capped_reply(severity: str, facility: dict | None) -> str`; `_TurnContext` dataclass (`conversation_id`, `capped`).
- Consumes: Task 4.

- [ ] **Step 1: Write the failing tests (Claude)** with a scripted fake client that records calls and returns a triage tool call, and an `InMemorySpendStore`:
  - Under the cap, `conversation_id` given: behaviour unchanged (two calls on a triage turn); tokens from each call's `usage` are added to the store (prompt + completion).
  - `conversation_id=None`: nothing recorded, no cap, unchanged.
  - Cap reached (store pre-filled to the cap) with fewer user turns than `TRIAGE_MIN_TURNS`: the call has `force_tool` set; the response has a severity, `turn_type == "triage"`, `cap_reached is True`, the text equals `capped_reply(...)` and contains `CAPPED_NOTE`; the fake saw **exactly one** call.
  - Cap reached with a facility: reply contains the facility name; without location: no facility named, mentions 211 per the existing no-facility rule.
  - Cap reached but the model returns no triage tool call: reply contains `SAFETY_LINE`, `severity is None`, `turn_type == "followup"`, `cap_reached is True`.
  - `capped_reply` for `emergent` mentions 911.
  - A store that fails open (total 0) leaves the agent working.
- [ ] **Step 2:** Run; expected fail.
- [ ] **Step 3: Implement (Claude).** Add one helper `_chat(ctx, **kwargs)` that calls `self._client.chat` and then `await store.add(id, prompt+completion)`; replace both existing `self._client.chat` calls with it; thread `_TurnContext` through `_run`, `_handle_triage`, `_generate_grounded_response`. In `respond`: compute `capped`, `force = ...or capped`, increment `LLM_CAP_REACHED` and log `conversation_cap_reached` when capped. Default store when none is passed: `RedisSpendStore(redis_client)` built lazily in `get_agent()` only; the constructor default is `None`, meaning no cap, so unit tests and the eval opt in explicitly.
- [ ] **Step 4:** Tests pass; `tests/llm` and `tests/test_chat.py` green.
- [ ] **Step 5:** Commit (after approval): `feat(triage): classify from what is known once a conversation reaches its token cap`

### Task 6: The guarded stack, route wiring and the safety line (Claude)

**Files:**
- Modify: `backend/services/llm_agent.py` (`build_guarded_client`, `get_llm_client`, `get_agent`), `backend/llm/groq_client.py` (remove the `tool_use_failed` retry, D3), `backend/routers/chat.py` (pass `conversation_id=session_id`; safety line in the generic failure text)
- Test: `backend/tests/llm/test_client_factory.py` (extend), `backend/tests/llm/test_groq_client.py` (replace the two retry-on-`tool_use_failed` tests with: a `tool_use_failed` 400 is raised after **one** call), `backend/tests/test_chat.py` (extend)

**Interfaces:**
- Produces: `build_guarded_client(provider: str, *, breaker: bool) -> BaseLLMClient` returning `Instrumented(Breaker?(Retrying(provider client built with max_retries=0)))`; both `get_llm_client` branches use it (`breaker=True`).
- Consumes: Tasks 2 and 3.

- [ ] **Step 1: Write the failing tests (Claude).**
  - Factory: stack order outermost first is Instrumented, Breaker, Retrying, raw (inspect the wrapped attributes); `breaker=False` omits the breaker; provider clients are built with `max_retries=0` in **single-provider mode too** (patch `_build_provider_client` and assert the argument).
  - Chain mode: first provider's breaker open raises `ProviderCircuitOpen`; the fallback answers from the second (use `FallbackLLMClient` with a failing and a good fake behind real decorators).
  - Groq: a `tool_use_failed` `BadRequestError` makes exactly one SDK call and propagates.
  - Route: with `get_agent().respond` patched to raise `ProviderCircuitOpen("groq")`, the turn returns HTTP 200, a saved assistant message containing `SAFETY_LINE` (911 and 211), `severity is None`; a patched exception with `status_code == 429` still returns the existing `busy` response; the route passes `conversation_id` equal to the session id (assert on the patched `respond` call).
- [ ] **Step 2:** Run; expected fail.
- [ ] **Step 3: Implement (Claude).** Keep `_build_provider_client(provider, max_retries)` and pass `0` everywhere. Replace the generic failure message in `_run_turn` with text ending in `SAFETY_LINE` (import from `services.llm_agent`).
- [ ] **Step 4:** `doppler run -- pytest tests -q` green (non-integration).
- [ ] **Step 5:** Commit (after approval): `feat(llm): run every provider call through the retry and breaker stack and show a safety line when none is available`

### Task 7: Eval path and manifest (Claude)

**Files:**
- Modify: `backend/scripts/symptom_eval/system_under_test.py` (guarded client, `InMemorySpendStore`, `conversation_id`), `backend/scripts/symptom_eval/conversation_runner.py` (pass a conversation id), `backend/scripts/symptom_eval/run_manifest.py`, `backend/scripts/symptom_eval/cli.py` (`build_manifest`), `backend/scripts/symptom_eval/domain.py` and `ablation.py` (persist `cap_reached` per turn, mirroring `graph_context_matched`), `backend/scripts/symptom_eval/dry_run.py` (fake accepts the new argument)
- Test: `backend/scripts/symptom_eval/tests/` (`test_run_manifest.py`, `test_system_under_test.py`, `test_conversation_runner.py`, `test_cli.py`, `test_ablation.py`, `test_dry_run.py` extended)

**Interfaces:**
- `SystemUnderTestPort.respond(patient_message, history, conversation_id: str) -> SystemTurnResult`; `SystemTurnResult.cap_reached: bool`; the runner builds the id as `f"{variant}:{provider}:{case_id}:{repeat}"` (check how those four values reach the runner today and pass them; if the runner does not have them, add parameters, do not parse strings).
- `RunManifest` gains `retry_max_attempts: int`, `retry_base_delay_seconds: float`, `conversation_token_cap: int`, `breaker_enabled: bool`, `breaker_failure_threshold: int`, `breaker_cooldown_seconds: float`, `capped_reply_sha256: str`. `breaker_enabled` is `False` in the eval (spec C11). `capped_reply_sha256` is `sha256_text(CAPPED_NOTE + SAFETY_LINE)`.

- [ ] **Step 1: Write the failing tests (Claude).**
  - Manifest: each new field is enforced on resume (change one, expect `ManifestMismatch` naming it); a pre-existing manifest without them is refused.
  - `build_manifest` reads the values from the same getters the agent uses (set `LLM_CONVERSATION_TOKEN_CAP=1234` in the test environment and see it in the manifest).
  - Adapter: builds its client with `build_guarded_client("groq", breaker=False)` (patch it) and an `InMemorySpendStore`; passes `conversation_id` to the agent; returns `cap_reached`.
  - Runner: two conversations with different ids do not share spend (in-memory store, cap reached in one only).
  - Ablation: a turn with `cap_reached=True` is written to the checkpoint and read back.
  - Dry run still passes with zero provider calls.
- [ ] **Step 2:** Run; expected fail.
- [ ] **Step 3: Implement (Claude).** Follow the step 1 pattern for the manifest. The adapter keeps pinning Groq regardless of ambient `LLM_PROVIDER`.
- [ ] **Step 4:** `doppler run -- pytest scripts -q` green, then `python -m scripts.symptom_eval.cli run-ablation --dry-run --variant lay --repeats 2 --no-judges --providers off,static` completes; record its output.
- [ ] **Step 5:** Commit (after approval): `feat(eval): run the retry policy and token cap in the harness and pin them in the run manifest`

### Task 8: Docs and close-out (Claude)

**Files:**
- Modify: `CHANGELOG.md` (tick step 2 items under "Sprint 23 — Started" with a one-line result; note D3 and the open risks), `docs/superpowers/plans/2026-10-14-llm-provider-budget.md` (add a status note at the top: the 429 cooldown is superseded by the breaker; the tokens-per-minute bucket stays deferred and plugs in between `Instrumented` and `Breaker`; Task 1, the chain configuration, is unaffected)

- [ ] **Step 1:** Make both edits. Run `graphify update .`.
- [ ] **Step 2:** Final check: `doppler run -- pytest tests -q` and the step 7 dry run once more.
- [ ] **Step 3:** Commit (after approval): `docs: close sprint 23 step 2 and mark the provider budget plan as partly superseded`

## Execution notes

- Tasks 2, 3, 4 are independent; they can go to Gemini one task per `claude-agy-orch` run on throwaway branches, Claude's tests committed first on each. Task 5 needs Task 4 merged; Task 6 needs Tasks 2, 3; Task 7 needs 5 and 6.
- Config for the pilot and the run: nothing is set in Doppler by this plan. Defaults apply; the owner sets `LLM_CONVERSATION_TOKEN_CAP` after the pilot.
- Not in this plan: pushing, opening a PR, merging into `feat/eval-hardening`.
