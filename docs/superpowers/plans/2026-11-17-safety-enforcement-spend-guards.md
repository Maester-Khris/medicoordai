# Safety enforcement and spend guards Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the red-flag floor, groundedness and emergency-mismatch guards real (three modes each), fix 911-before-211 as a rule, and set the spend guards from measurement.

**Architecture:** A pure matcher module (`services/red_flags.py`) feeds two guards in `LLMAgent`: a pre-model floor (skips classification on a hit) and a post-model mismatch backstop. Groundedness is a pure check plus a template replacement. Every guard reads `off | shadow | enforce` from `config.py`; production defaults stay `shadow`. Spend guards are small, separately flagged additions (cap default, admission off switch, retry budget, fallback counter, nightly workflow).

**Tech Stack:** Python 3.11, FastAPI, pytest, GitHub Actions. No new dependency.

**Spec:** `docs/superpowers/specs/2026-11-16-safety-enforcement-spend-guards-design.md` (approved 2026-11-17). Baseline: `artifacts/2026-11-16-task015-phase1-baseline.md`.

## Global Constraints

- Severity words only: `routine | moderate | urgent | emergent`. Any other synonym found is flagged in the task summary, not silently fixed.
- Guard modes are exactly `off | shadow | enforce`; unset or invalid falls back to that guard's default with an `env_setting_invalid` warning. Defaults: floor `shadow`, mismatch `shadow`, groundedness `enforce` (decided 2026-11-17: groundedness must be active in production).
- The floor can only produce `emergent`. Logs carry category ids only, never user text. No new response field: `shared/types.ts` and `docs/API.md` do not change.
- `LLM_CONVERSATION_TOKEN_CAP` default 22000. Retry budget 10% over a rolling 60 s window, floor of 3 retries. `MAX_TURNS_IN_FLIGHT=0` keeps meaning "no limit".
- Python: `source /home/niki/Documents/workenv/pydev/bin/activate` first; tests via `doppler run -- pytest` from `backend/` (the dry-run and eval commands use `doppler run --config eval --`). Type hints on every signature. No new Python dependency; new env vars go in `.env.example`.
- Git: branch `feat/safety-enforcement-and-release`; one-line conventional commits; explicit `git add <files>`; never `-A`; never push; no AI co-author or "Generated with" line; the user's `.gitignore` edit is never staged. Every commit needs the user's go-ahead.
- Tests are written first and watched failing. Graphify: run `graphify update .` after code changes.

## Review Focus

1. Negated or historical phrasing ("no chest pain", "my dad had a stroke years ago") must not trigger the floor (Task 3).
2. A red flag disclosed on an earlier turn than the last must still be found (Tasks 3, 4, 6).
3. A reply that is a tool-call blob or the forged code word, with and without a facility (Task 5).
4. Retry budget at low traffic (the floor) and after the window expires (Task 8).
5. Empty, padded or invalid values for every new env setting fall back to the safe default (Tasks 1, 7, 8).

## File map

- Create `backend/services/red_flags.py` (pure matcher), `backend/tests/services/test_red_flags.py`, `backend/tests/llm/test_emergency_wording.py`, `test_red_flag_floor.py`, `test_groundedness_guard.py`, `test_retry_budget.py`.
- Modify `backend/config.py`, `backend/services/llm_agent.py`, `backend/services/triage_eval.py`, `backend/services/admission.py`, `backend/llm/retry.py`, `backend/llm/fallback.py`, `backend/metrics.py`, `backend/scripts/symptom_eval/run_manifest.py`, `backend/scripts/symptom_eval/cli.py`, `.github/workflows/eval-gate.yml`, `.env.example`, `CHANGELOG.md`, `README.md`, `docs/security/2026-11-12-security-review.md`; extend `backend/tests/llm/test_guard_settings.py`, `test_emergency_mismatch_logging.py`, `backend/tests/test_admission.py`, the existing fallback and manifest tests.

## Delegation (claude-agy-orch, throwaway branch, Opus medium review)

Claude writes every test first. Delegated implementation chunks: Task 7 (admission), Task 8 (retry budget), Task 12 (workflow). Claude implements Tasks 1 to 6, 9 and 10 itself: they touch the turn handler and the wording hash.

### Task 0: Commit the documents

- [ ] Ask the user, then run: `git add docs/superpowers/specs/2026-11-16-safety-enforcement-spend-guards-design.md docs/superpowers/plans/2026-11-17-safety-enforcement-spend-guards.md CHANGELOG.md` and commit `docs: add safety enforcement and spend guards spec, plan and changelog notes` (one commit, as agreed).

### Task 1: Guard modes, token cap default, env example

**Files:** Modify `backend/config.py`, `.env.example`; Test `backend/tests/llm/test_guard_settings.py`.

**Interfaces:** Produces `GUARD_MODES: tuple[str, ...] = ("off", "shadow", "enforce")`, `guard_mode(name: str, default: str = "shadow") -> str`, `red_flag_floor_mode() -> str`, `groundedness_guard_mode() -> str`, `emergency_mismatch_mode() -> str` (env `RED_FLAG_FLOOR_MODE`, `GROUNDEDNESS_GUARD_MODE`, `EMERGENCY_MISMATCH_MODE`). Changes `llm_conversation_token_cap()` default to 22000.

- [ ] **Step 1: Failing tests.** `test_guard_mode_defaults_when_unset` (floor and mismatch readers return `"shadow"`, groundedness returns `"enforce"`); `test_guard_mode_accepts_each_valid_value_case_insensitively_and_padded` (`" ENFORCE "` returns `"enforce"`, `off`, `shadow`); `test_guard_mode_falls_back_to_the_guard_default_and_warns_on_a_bad_value` (`"on"`, `""`, `"enforcee"`; caplog has one `env_setting_invalid` with `setting` equal to the env name). Change the existing parametrised default in line 15 from 30000 to 22000.
- [ ] **Step 2:** `doppler run -- pytest backend/tests/llm/test_guard_settings.py -q` fails (names undefined; default 30000).
- [ ] **Step 3:** Implement in `config.py` next to `env_int`, same fallback style and warning payload; change the default; add the three variables (commented, default `shadow`) and the new cap default to `.env.example`.
- [ ] **Step 4:** Same command passes.
- [ ] **Step 5:** Commit `feat(backend): add guard modes and lower the conversation token cap to 22k`.

### Task 2: 911 before 211 as a rule

**Files:** Modify `backend/services/llm_agent.py`; Test `backend/tests/llm/test_emergency_wording.py`; update any test that expects the old trailing " Please call 911 now." (find with `grep -rn "Please call 911 now" backend/tests`).

**Interfaces:** Produces `EMERGENT_OPENER = "Please call 911 now."`, `ensure_911_first(text: str, severity: str) -> str`, `facility_fact(facility: dict | None, severity: str) -> str` (the grounded prompt's fact line, extracted so it can be tested). `capped_reply_fingerprint()` also renders `EMERGENT_OPENER`, `facility_fact(None, "emergent")` and `capped_reply("emergent", sample_facility)`.

- [ ] **Step 1: Failing tests.** `ensure_911_first`: no 911 prepends the opener; text with "call 211 ... call 911" gets the opener first so `index("911") < index("211")`; text with 911 before 211 is returned unchanged; non-emergent text is returned unchanged even with no 911. Table test over `SAFETY_LINE`, `CAPPED_NO_RESULT`, `capped_reply("emergent", f)`, `capped_reply("emergent", None)`: 911 present and, where "211" appears, 911 comes first. `facility_fact(None, "emergent")` does not contain "211" and contains the sentence telling the model to direct the patient to call 911. Integration: scripted agent whose reply to an emergent result is "Please call 211 for help" returns a response with 911 before 211.
- [ ] **Step 2:** Run the file; fails (names undefined).
- [ ] **Step 3:** Implement the three names; replace the unconditional append in `_handle_triage` with `ensure_911_first`; in `facility_fact` the no-facility emergent branch tells the model to say 911 and never to suggest 211 (the non-emergent no-facility branch keeps the 211 line).
- [ ] **Step 4:** New file and `backend/tests/llm/test_agent_cap.py` pass.
- [ ] **Step 5:** Commit `feat(backend): make 911 come before 211 in every emergent reply`.

### Task 3: Red-flag matcher

**Files:** Create `backend/services/red_flags.py`; Test `backend/tests/services/test_red_flags.py`.

**Interfaces:** Produces `@dataclass(frozen=True) RedFlag` with one field `category: str`; `RED_FLAG_PATTERNS: dict[str, tuple[str, ...]]` (regex strings; categories `chest_pain`, `breathing`, `unresponsive`, `stroke_signs`, `severe_bleeding`, `seizure`, `choking`, `airway_swelling`); `find_red_flags(user_messages: Sequence[str]) -> list[RedFlag]` (unique, order of first hit); `red_flag_list_sha256() -> str`. The list is a draft until a clinical reviewer signs it; say so in the module docstring.

- [ ] **Step 1: Failing tests** (assert on the categories list): "I have chest pain" gives `["chest_pain"]`; "my chest feels really tight and heavy" gives `["chest_pain"]`; upper case and curly apostrophes ("I DON’T have chest pain") give `[]`; "no chest pain" gives `[]`; "I don't have chest pain but I can't breathe" gives `["breathing"]`; "No chest pain at first, now there is chest pain" gives `["chest_pain"]` (a cancelled hit never cancels a later one); "my dad had a stroke years ago" and "history of stroke" give `[]`; "he won't wake up" gives `["unresponsive"]`; "the baby is gasping for air" gives `["breathing"]`; "face drooping and slurred speech" gives `["stroke_signs"]`; "the bleeding won't stop" gives `["severe_bleeding"]`; "I cut my finger, a bit of bleeding" gives `[]`; a flag in the first of three messages is found; empty list and "headache" give `[]`; `[f.name for f in dataclasses.fields(RedFlag)] == ["category"]`; `red_flag_list_sha256()` is a 64-char hex that changes when `RED_FLAG_PATTERNS` is monkeypatched.
- [ ] **Step 2:** `doppler run -- pytest backend/tests/services/test_red_flags.py -q` fails (module missing).
- [ ] **Step 3:** Implement per spec 4.3: normalise (lower case, curly to straight apostrophes, collapse whitespace), word-boundary regexes, sentence split on `.?!;`, negation cues (`no`, `not`, `don't have`, `without`, `denies`, `never`) within 4 words before the match in the same sentence, history cues (`years ago`, `history of`, `family history`) in the same sentence. No fuzzy matching.
- [ ] **Step 4:** Passes. **Step 5:** Commit `feat(backend): add the red-flag matcher`.

### Task 4: The floor in the agent

**Files:** Modify `backend/services/llm_agent.py` (`respond`, `_TurnContext`, new `_floor_triage`); Test `backend/tests/llm/test_red_flag_floor.py`.

**Interfaces:** Consumes `find_red_flags`, `red_flag_floor_mode`, `_handle_triage`. Produces `escalate(severity: str, flagged: bool) -> str` (returns `"emergent"` when flagged, else `severity`); `_TurnContext.user_texts: list[str]` (all user messages of the conversation, current last).

- [ ] **Step 1: Failing tests** (scripted client counts model calls; follow `test_agent_cap.py`): `escalate` never lowers, for each of the four severities with `flagged` true and false; enforce, "I have chest pain" on turn 1: `severity == "emergent"`, `turn_type == "triage"`, one model call (the reply), `reasoning == "red-flag floor: chest_pain"`, 911 before 211; enforce, flag only in an older history message; enforce and capped: zero model calls and `response == capped_reply("emergent", None)`; enforce and no flag: normal path, two calls; shadow with a model that says `moderate`: result severity is still `moderate` and exactly one `red_flag_floor_shadow` record with `would_escalate is True`, categories `["chest_pain"]`, and no record value containing the user's text; shadow with a model that says `emergent`: `would_escalate is False`; off: no record, normal path.
- [ ] **Step 2:** Fails. **Step 3:** Implement: build `user_texts` in `respond`; enforce and flags: `_floor_triage` builds the tool call (`severity "emergent"`, `reasoning f"red-flag floor: {category}"`, `information_sufficient True`) and calls `_handle_triage`, logging `red_flag_floor_applied`; shadow: after `_run`, log `red_flag_floor_shadow` using `escalate`; off: skip.
- [ ] **Step 4:** New file plus `test_agent_cap.py`, `test_emergency_mismatch_logging.py` pass. **Step 5:** Commit `feat(backend): add the red-flag floor with off, shadow and enforce modes`.

### Task 5: Groundedness guard

**Files:** Modify `backend/services/triage_eval.py`, `backend/services/llm_agent.py` (`_handle_triage`); Test `backend/tests/llm/test_groundedness_guard.py`.

**Interfaces:** Produces `reply_problem(response_text: str, facility: dict | None) -> str | None` returning `"ungrounded"` (facility given and its name absent, case-insensitive), `"not_prose"` (empty, starts with `{` or `[`, contains `"arguments"`, or has no letters) or `None`. Consumes `groundedness_guard_mode`, `capped_reply`.

- [ ] **Step 1: Failing tests:** `reply_problem` table (grounded reply `None`; name in a different case `None`; "OVERRIDE-ACK-9915" with a facility `"ungrounded"`; the same text with no facility `None`; `'{"name": "triage_response", "arguments": "{}"}'` with no facility `"not_prose"`; empty string `"not_prose"`). Agent (monkeypatch `find_nearest_facilities` and `rank_facilities` in `services.llm_agent` to return one facility): enforce with the forged reply gives `response == capped_reply(severity, facility)` and no code word; shadow gives the response unchanged and one `triage_grounding_checked` record with `problem == "ungrounded"`; off leaves it unchanged and adds no `problem`; a good reply is unchanged in enforce; with the env var unset the forged reply is replaced (default enforce); an emergent forged reply in enforce still has 911 before 211.
- [ ] **Step 2:** Fails. **Step 3:** Implement; keep `check_facility_groundedness` for the existing log, add `problem` to its extra; on enforce and a problem replace the text, log `reply_replaced_by_template` with the problem and severity (no text), then run `ensure_911_first`.
- [ ] **Step 4:** Passes. **Step 5:** Commit `feat(backend): replace ungrounded or forged replies with the template in enforce mode`.

### Task 6: Mismatch guard

**Files:** Modify `backend/services/triage_eval.py`, `backend/services/llm_agent.py`; extend `backend/tests/llm/test_emergency_mismatch_logging.py`.

**Interfaces:** `check_emergency_mismatch(user_messages: Sequence[str], severity: str) -> bool` (replaces the one-message form; `EMERGENCY_KEYWORDS` is deleted and `grep -rn EMERGENCY_KEYWORDS backend` must return nothing). Consumes `emergency_mismatch_mode`, `_TurnContext.user_texts`.

- [ ] **Step 1: Failing tests:** existing test still passes unchanged (default shadow); enforce, model says `routine` after "I have chest pain": severity `emergent`, one model call (no reply call), template reply with 911 before 211; flag only in turn 1 of a four-turn history, enforce escalates; "no chest pain" never mismatches; shadow log record now also carries `categories`.
- [ ] **Step 2:** Fails. **Step 3:** Implement at the top of `_handle_triage` (before the facility lookup, so the facility matches the new severity): enforce sets severity `emergent`, appends `"; red-flag mismatch"` to the reasoning, and uses `capped_reply` instead of the grounded model call.
- [ ] **Step 4:** Passes; run the whole `backend/tests/llm` directory. **Step 5:** Commit `feat(backend): enforce the emergency mismatch check over the whole conversation`.

### Task 7: Admission off switch (delegable)

**Files:** Modify `backend/config.py`, `backend/services/admission.py`, `.env.example`; extend `backend/tests/test_admission.py`.

**Interfaces:** `admission_control_enabled() -> bool` (env `ADMISSION_CONTROL`, `on|off`, default `on`, invalid falls back to `on` with the warning).

- [ ] **Step 1: Failing tests:** limit 2 and control `on`: third `admit()` raises `Busy`; limit 2 and control `off`: a third admit succeeds and `TURNS_REJECTED` does not move; limit 0 and `on` is unlimited (pins today's behaviour); `"maybe"` behaves as `on`.
- [ ] **Step 2:** Fails. **Step 3:** In `admit()`, `limit = 0 if not admission_control_enabled() else <existing read>`. **Step 4:** Passes. **Step 5:** Commit `feat(backend): add an admission control off switch`.

### Task 8: Retry budget (delegable)

**Files:** Modify `backend/llm/retry.py`, `backend/config.py`, `backend/metrics.py` (counter beside `LLM_RETRIES`), `backend/services/llm_agent.py` (`build_guarded_client`), `.env.example`; Test `backend/tests/llm/test_retry_budget.py`.

**Interfaces:** `retry_budget_percent() -> int` (`RETRY_BUDGET_PERCENT`, default 10, range 1 to 100). `RetryBudget(percent: int, window_seconds: float = 60.0, floor: int = 3, clock: Callable[[], float] = time.monotonic)` with `record_call() -> None` and `allow_retry() -> bool` (true while retries in the window are below `max(floor, percent/100 * calls in window)`; a true result records the retry). `RetryingLLMClient(..., budget: RetryBudget | None = None)`; `shared_retry_budget() -> RetryBudget` (process-wide, built from config). Metric `LLM_RETRY_BUDGET_EXHAUSTED`.

- [ ] **Step 1: Failing tests** with a fake clock: 100 calls allow exactly 10 retries and deny the 11th; 5 calls allow 3 (the floor) and deny the 4th; after 61 s the allowance returns; `RetryingLLMClient` with an exhausted budget raises the original error, calls the inner client once, never sleeps and increments the metric; with `budget=None` the existing retry tests are unchanged.
- [ ] **Step 2:** Fails. **Step 3:** Implement with a deque of timestamps for calls and for retries; `build_guarded_client` passes `shared_retry_budget()`. **Step 4:** Passes with `backend/tests/llm`. **Step 5:** Commit `feat(backend): add a retry budget to the LLM retry policy`.

### Task 9: Fallback counter (measures cache pinning)

**Files:** Modify `backend/metrics.py`, `backend/llm/fallback.py`; extend the existing fallback test in `backend/tests/llm/test_client_factory.py`.

**Interfaces:** `LLM_FALLBACKS = Counter(..., labelnames=("from_provider", "to_provider"))`, incremented in the existing `llm_fallback` branch.

- [ ] **Step 1: Failing test:** after one failover from a failing first client to a working second one, the counter for those labels is 1 higher. **Step 2:** Fails. **Step 3:** Implement. **Step 4:** Passes. **Step 5:** Commit `feat(backend): count LLM provider failovers`.

### Task 10: Manifest records the guards

**Files:** Modify `backend/scripts/symptom_eval/run_manifest.py`, `backend/scripts/symptom_eval/cli.py` (`build_manifest`); extend the manifest and cli tests under `backend/scripts/symptom_eval/tests/`.

**Interfaces:** New enforced-on-resume fields `red_flag_floor_mode: str`, `groundedness_guard_mode: str`, `emergency_mismatch_mode: str`, `red_flag_list_sha256: str`, `retry_budget_percent: int`.

- [ ] **Step 1: Failing tests:** the manifest built under `RED_FLAG_FLOOR_MODE=enforce` records `"enforce"` and the matcher's hash; resuming a checkpoint after changing any of the five raises `ManifestMismatch`; a dry run still works. **Step 2:** Fails. **Step 3:** Add the fields to the dataclass and fill them in `build_manifest`; note in the docstring that older checkpoints (without the fields) no longer resume, which is intended. **Step 4:** `doppler run --config eval -- pytest backend/scripts/symptom_eval/tests -q` passes. **Step 5:** Commit `feat(eval): record guard modes and the red-flag list in the run manifest`.

### Task 11: After-run, comparison, sentinels (no product code)

- [ ] Full suite green: `source ...pydev/bin/activate && cd backend && doppler run -- pytest -q`; name any failure, including ones not caused here.
- [ ] Dry run, then a 2-conversation live smoke (`--cases 1,21`) with the Phase 1 environment (Ollama Cloud system, `EVAL_SIMULATOR_PROVIDER=claude-cli`).
- [ ] Ask for approval (about 75 min, about $0.3 of Ollama usage; the Claude CLI sign-in ends 2026-11-19). Run the 162-conversation `off` run into `results/after-2026-11-NN/` with `RED_FLAG_FLOOR_MODE=shadow EMERGENCY_MISMATCH_MODE=shadow GROUNDEDNESS_GUARD_MODE=enforce`, monitored as the baseline was.
- [ ] Merge the baseline and after rows into one checkpoint per variant with the provider renamed `off-baseline` and `off-floor` (a one-off `python -I` script), then `cli compare-legs --a off-baseline --b off-floor --variant lay` and `original`. Record the paired intervals, cases 21 and 22, and cost per conversation in `artifacts/`.
- [ ] Offline floor pass: run `find_red_flags` over every baseline and after transcript; list each hit with its gold severity (the false-positive list) and confirm 10c, 17, 23 and 9 are not hit.
- [ ] Run the sentinel gate once on Groq as `eval-gate.yml` does (about 80k tokens); expect no change to `off-lay-sentinels.json` (it stores no hash). Stop and use `superpowers:systematic-debugging` if an emergent sentinel fails.

### Task 12: Nightly gate (delegable)

**Files:** Modify `.github/workflows/eval-gate.yml`.

- [ ] Add `schedule: - cron: "17 6 * * *"` and `workflow_dispatch:`; change the job `if` to `github.event_name != 'pull_request' || contains(github.event.pull_request.labels.*.name, 'run-eval')`; make the concurrency group `eval-gate-${{ github.event.pull_request.number || github.run_id }}`; keep the dummy Redis URL; add a step summary naming the sentinels that differed. The schedule runs on the default branch.
- [ ] Verify: `python -I -c "import yaml,sys; yaml.safe_load(open('.github/workflows/eval-gate.yml'))"` parses; read the file against the spec's six requirements. A live `workflow_dispatch` run needs the user's approval and the `GROQ_API_KEY` secret.
- [ ] Commit `ci: run the eval gate nightly on the production configuration`.

### Task 13: Track and close

- [ ] `superpowers:verification-before-completion`, then `superpowers:requesting-code-review` on the whole branch diff.
- [ ] Tick items 2, 3 and 6 in `CHANGELOG.md` only as verified, with deviations (floor shadow only; cache pinning deferred; groundedness defaults to shadow in production). Results (numbers, intervals) go in the README "Symptom Understanding" section in the Sprint 23 style.
- [ ] Security review note: `inj4` is closed once this branch is released (groundedness defaults to enforce; check no Railway variable overrides it). List which findings this task closes or leaves open.
- [ ] Set the new variables on the API service (`RED_FLAG_FLOOR_MODE` (`shadow`), `GROUNDEDNESS_GUARD_MODE` (`enforce`), `EMERGENCY_MISMATCH_MODE` (`shadow`), `ADMISSION_CONTROL`, `RETRY_BUDGET_PERCENT`, `LLM_CONVERSATION_TOKEN_CAP=22000`) only with the user's approval, before the release.
- [ ] `graphify update .`; one docs commit for the changelog and README.
