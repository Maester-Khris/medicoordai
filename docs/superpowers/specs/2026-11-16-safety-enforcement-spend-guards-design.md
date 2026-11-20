# Safety enforcement and spend guards — design (Sprint 24, task 015)

Date: 2026-11-16 · Branch: `feat/safety-enforcement-and-release` · Status: **approved by the user 2026-11-17 with the changes in section 3**
Task: `.agents/tasks/015_SAFETY_ENFORCEMENT_AND_SPEND_GUARDS.md` · Baseline: `artifacts/2026-11-16-task015-phase1-baseline.md`

Marking: **Decided** = the user said so. **Proposed** = my call with a reason, for the user to accept or change.

## 1. Intent

Sprint 23 left three safety checks that only log (red-flag keywords, groundedness, emergency mismatch) and four spend limits that are guesses. This task makes the safety guarantees hold in code instead of in the prompt, and sets the limits from measurement. The rules the user cares about: an emergency is never answered slowly, never without the 911 line, and a model reply that was forged or ungrounded never reaches the patient.

## 2. Goals, non-goals, anti-goals

Goals
- A deterministic red-flag floor that can only escalate to `emergent`, on the production path (no graph).
- Groundedness and emergency-mismatch enforcement, each with its own `off | shadow | enforce` mode.
- For an emergent reply, 911 always comes before any 211 (a rule with a test, not a patch).
- Token cap, admission off switch and retry budget set from measurement; a nightly gate on the production configuration.

Non-goals (see the task's Out of Scope): retrieval challengers, graph v3, agentic sufficiency, PII detection, staging DB separation, RLS, judge validity, frontend work, the release itself.

Anti-goals (a failure even if it technically works)
- Claiming the floor fixes cases 10c, 17, 23 or 9 (it does not; see 4.4).
- A floor that lowers a severity, or that logs user text.
- Silent over-triage: a floor that sends routine complaints to 911 without the cases being listed and published.
- A second re-baseline of the wording hash.

## 3. Decided (by the user)

- The floor is a **narrow safety net**: a small, clinically reviewed list of unambiguous red flags. It is a production guarantee, not a way to move the vignette numbers.
- **Approach B**: a pure matcher module; on a floor hit the agent skips the model's classification call and builds the emergent result itself. The three guards stay plain functions plus a mode setting each (no guard framework).
- **2026-11-17 answers:** (1) no clinical reviewer is named, so the red-flag floor stays **shadow only** in this task; enforce is a later decision once a reviewer signs the list. The mismatch guard uses the same list, so it also stays shadow. (2) Cache pinning is deferred (count first); the CHANGELOG must say so. (3) Groundedness must be active in production, so its default is `enforce` ("shadow only" applied to the floor and the CI gate). (4) The CHANGELOG line in the sand is updated in the same commit as the spec and the plan (one commit: spec, plan, CHANGELOG). The token cap evidence is saved in `artifacts/2026-11-16-task015-phase1-baseline.md`; it is the "before" number for the agentic-conversation sprint.
- Provider and patient for the baseline: Ollama Cloud `gpt-oss:120b-cloud` as the system, `claude -p` Haiku 4.5 as the patient (the after-run uses the same, so the comparison is paired).

## 4. A. Red-flag floor

### 4.1 Approaches considered
- A. Post-model only: smallest change, but the model still asks follow-ups first, so a red flag on turn 1 gets the 911 answer late; and if the model asks a question instead of classifying, the floor has nothing to raise.
- **B. Pre-model short-circuit (chosen).** One pure function scans the whole conversation before the model runs. A hit skips the classification call, so an emergency costs one model call instead of two (the reply), and arrives on turn 1.
- C. Injected guards object with a policy class per guard: cleaner on paper, an abstraction for three guards that share one turn handler. Build it only if a fourth guard appears.

### 4.2 Behaviour
- **Module:** `backend/services/red_flags.py` (pure, no I/O): the pattern list and `find_red_flags(user_messages: list[str]) -> list[RedFlag]` where `RedFlag` has a category id only.
- **Scope:** all user turns of the conversation (history plus the current message), never assistant text. Today's mismatch check reads only the last message; a symptom disclosed on turn 2 would be missed.
- **Enforce, on a hit:** skip classification; build the tool arguments `severity="emergent"`, `reasoning="red-flag floor: <category>"`; run the existing `_handle_triage` (facility lookup, grounded reply or the capped template, groundedness check). The minimum-turns gate does not apply (emergent already bypasses it).
- **Shadow, on a hit:** run the normal path; after the model result, log `red_flag_floor_shadow` with the categories, the model's severity and `would_escalate` (true when the model said anything below emergent). This is how the false-positive list is produced.
- **Off:** not evaluated.
- **Escalate-only is structural:** the floor can only produce `emergent`; a miss leaves the model's path untouched. A test proves no input lowers a severity.
- **No new response field.** Logging only: `red_flag_floor_applied` / `red_flag_floor_shadow` with category ids, mode and `user_turns`, never the user's text. `shared/types.ts` and `docs/API.md` do not change.

### 4.3 Pattern list and matching (proposed)
- **Source:** one list, `RED_FLAG_PATTERNS`, replaces `EMERGENCY_KEYWORDS` in `triage_eval.py` (DRY: the floor and the mismatch check share it). Starts from the six existing keywords and adds lay wording for the same conditions: chest pain or pressure, cannot breathe or gasping, unconscious or will not wake or unresponsive, stroke signs (face drooping, slurred speech, sudden one-sided weakness), severe or uncontrolled bleeding, ongoing seizure, choking, throat or tongue swelling with trouble breathing. About 10 categories, each with a few lay phrasings. The list is a **draft until reviewed**.
- **Normalisation:** lower case, curly to straight apostrophes, collapsed whitespace.
- **Matching:** word-boundary regexes. No fuzzy matching in v1: it raises false positives; a fixed list of common misspellings is added only when the eval shows a miss.
- **Negation:** a hit is cancelled when a negation cue (`no`, `not`, `don't have`, `without`, `denies`, `never`) is within 4 words before it in the same sentence. A cancelled hit never cancels a later, separate hit. History cues (`years ago`, `history of`, `family history`) cancel as well.
- **False positives accepted on purpose:** the floor errs toward 911. They are counted, not hidden: over-triage is the counter-metric and shadow mode lists them.
- **Injection:** the matcher reads user text only and can only push toward emergent, the safe direction; a user who writes "chest pain" to game the system gets the 911 line.

### 4.4 What the floor will and will not do (from the baseline)
The below-emergent cases at baseline are 10c (stiffness after a crash), 17 (flank pain, vomiting), 23 (toddler, fever, vomiting, loose stools) and 9 (eye pain, halos around lights). None contains a pattern. Expect the floor to leave them unchanged. They are a model-quality and gold-label question, listed as a known gap and not part of this task.

### 4.5 Checks
- Cases 21 and 22 with the floor on (both hold at baseline on Ollama; 22 had one urgent in the original variant).
- Offline false-positive measure: run the matcher over every non-emergent baseline transcript; list each hit.
- Reviewer: none named yet (decided 2026-11-17). The floor and the mismatch guard stay in shadow, and moving either to enforce needs a named reviewer to sign the list first. The enforce code and its tests still ship, so the switch is one env var later.

## 5. B. Groundedness and emergency-mismatch enforcement

- **Groundedness (`GROUNDEDNESS_GUARD_MODE`).** Ungrounded means: a facility was provided and its name is missing from the reply; or the reply is not prose (empty, a JSON or tool-call blob, no letters). In enforce the reply is replaced by `capped_reply(severity, facility)`. This closes the open Medium-low finding `inj4` (forged closing tags that made the reply the code word `OVERRIDE-ACK-9915`; `docs/security/2026-11-12-security-review.md`, "The 6 flags"). With no facility, only the non-prose check applies.
- **Mismatch (`EMERGENCY_MISMATCH_MODE`).** Same matcher, post-model backstop over the whole conversation. In enforce it escalates to emergent and answers with the emergent template (no second model call: deterministic and cheaper). With the floor on, it mostly fires only when the floor is off or shadow.
- **911 before 211 (proposed rule).** For an emergent reply the invariant is: 911 present, and if 211 is present, 911 comes first. `ensure_911_first(text, severity)` checks the invariant and, only when it fails, prepends `Please call 911 now.`. This replaces the unconditional after-the-fact append. The grounded-reply prompt for an emergent result also stops saying "call 211" (that wording is only for non-emergent, no-location). Reason: the prefix is deterministic and testable; the prompt is advisory. A test runs the invariant over every template and over fake model replies that put 211 first.
- **Modes:** `off | shadow | enforce`, default `shadow` for the floor and the mismatch guard, which cannot leave shadow without a clinical reviewer (4.5). **Groundedness defaults to `enforce`** (decided 2026-11-17: it must be active in production; it does not depend on the unreviewed list and a replaced reply fails toward the safe template). An invalid value falls back to the default with a warning (the `env_int` pattern in `config.py`).
- **Wording hash, once.** `capped_reply_fingerprint()` is extended to include the new opener, the emergent template and the grounded prompt text; the run manifest also records the guard modes and a hash of the pattern list. The hash changes in one commit, after every wording change.

## 6. C. Cost guards

- **Token cap.** `LLM_CONVERSATION_TOKEN_CAP` default 30,000 to **22,000**. Data: baseline cumulative tokens per conversation (162 conversations, per-turn counters summed): mean 4.4k, p95 6.3k, max 7.2k. Sprint 23 measured mean about 5.2k, max about 11k on other runs. 2x the larger max = 22k. Set on the API service; the worker does not read it. (The per-turn numbers in the baseline note are not the cap's unit: the cap counts a conversation's total.)
- **Admission off switch.** New `ADMISSION_CONTROL=on|off`, default `on`. `off` forces "no limit" whatever `MAX_TURNS_IN_FLIGHT` holds, so an operator can switch it off in an incident without losing the measured limit. `MAX_TURNS_IN_FLIGHT=0` keeps meaning "no limit" (a test pins this so it cannot change by accident). No measured limit is set in this task.
- **Retry budget.** Retries are allowed while retries stay under `RETRY_BUDGET_PERCENT` (default 10) of calls in a rolling 60 s window, with a floor of 3 so low traffic is not starved. Process-local (each replica protects itself, like admission). Exhausted: raise the original error, count it. "No retry after the first streamed token": the API clients do not stream today (`chat` returns a whole response), so there is nothing to guard; noted, no code.
- **Cache pinning (deferred, approved 2026-11-17; to be stated in the CHANGELOG).** `FallbackLLMClient` is stateless and always starts at the primary, so a conversation returns to the primary on the next turn; failover is rare. Pinning would add shared state for a case we cannot yet size. Now: count conversations that saw more than one provider (a field on the existing `llm_fallback` log). Build pinning only if that count is meaningful. This is first in the sprint's cut order anyway.
- **Nightly gate.** Add `schedule` (daily, UTC night) and `workflow_dispatch` to `.github/workflows/eval-gate.yml`, same sentinels, same Groq calibration, same dummy Redis URL so production counters are never written. Needs the `GROQ_API_KEY` secret (still an owner action). On failure the job fails (GitHub notifies) and the step summary names the sentinels that differed; no automatic issue. About 80k Groq tokens per run against the 200k daily limit, so a same-day PR-label run still fits. Last task; needs the re-baselined sentinels.

## 7. D. Measurement and line in the sand

- **Run:** the same 162-conversation `off` run as the baseline, same system and patient, with floor `shadow`, mismatch `shadow` and groundedness `enforce` (my call: groundedness does not depend on the unreviewed list, and it closes `inj4`). Floor and mismatch effects are read from the shadow log (`would_escalate` cases) and the offline pass over the baseline transcripts, so no enforce run of the floor is needed now. Paired against `baseline-2026-11-16` by merging the two checkpoints with the leg renamed `off-baseline` and `off-floor`, then `compare-legs` (no harness change).
- **OMTM:** under-triage on the 27 vignettes (both variants), paired, with interval. Counters: over-triage and cost per conversation (tokens, and dollars from the Ollama price list).
- **Line in the sand (proposed, replaces the CHANGELOG wording):** (1) every case that was emergent 3/3 at baseline stays emergent 3/3 (trivially true for a shadow floor; it becomes a real test when the floor is enforced later); (2) under-triage no worse than baseline beyond the paired interval; (3) every floor-caused over-triage is listed; (4) production smoke green by Nov 20. The four known gaps are published as a known gap, not claimed fixed. The CHANGELOG sprint line ("no emergent vignette classified below emergent") is unreachable with a narrow floor and needs a separate edit, with approval.
- **Miss response (unchanged from the task):** floor and groundedness stay in shadow and the false positives are published; ship the wording fix, the off switch and the mobile fix.
- **Reversible:** every guard has its own flag; the floor can only escalate; fixed-turn stays the default.

## 8. E. Interfaces and contracts

- No response field is added; `shared/types.ts` and `docs/API.md` stay as they are. Severity words are only `routine | moderate | urgent | emergent`.
- New env vars (in `.env.example`, set on the API service; the worker does not read them): `RED_FLAG_FLOOR_MODE`, `GROUNDEDNESS_GUARD_MODE`, `EMERGENCY_MISMATCH_MODE`, `ADMISSION_CONTROL`, `RETRY_BUDGET_PERCENT`. Changed default: `LLM_CONVERSATION_TOKEN_CAP`.
- Changed signature: `check_emergency_mismatch` takes the list of user messages (tests extended, not replaced).
- No new Python dependency, no new npm package.

## 9. Design lenses (skills)

- Clean architecture: the matcher is pure and sits in the inner circle; modes come from `config.py`; the turn handler only wires them. Dependencies point inward.
- Pragmatic programmer: one pattern list (DRY), tracer bullet first (floor in shadow end to end), reversibility through per-guard flags.
- Clean code: small named functions, constants for the opener and modes, one concept per test.
- Release It: bounded retries (budget, floor), off switch for admission, an enforcement that fails toward the safe side.
- Not used: `ddia-systems` (pinning deferred, no consistency design needed).

## 10. Left to the builder

Exact regex wording per category; where the guard-mode helper lives inside `config.py`; log field names; the unit of the retry window clock in tests; the exact sentinel re-baseline procedure (check whether `off-lay-sentinels.json` stores a manifest hash); which plan chunks go to `claude-agy-orch` (proposal: the nightly workflow and the retry budget; Claude keeps the floor and the turn-handler changes).

## 11. Open questions

None. Resolved 2026-11-17: reviewer (none yet, shadow only), cache pinning (deferred), CHANGELOG edit (same commit as spec and plan).
Still owed outside this task: a named clinical reviewer, before the floor or the mismatch guard moves to enforce.
