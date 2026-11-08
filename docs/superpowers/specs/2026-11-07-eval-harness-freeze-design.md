# Eval harness freeze (Sprint 23, step 1) — Design

Date: 2026-11-07 · Branch: `feat/eval-hardening` · Source of scope: `CHANGELOG.md`, "Sprint 23 — Started", step 1.

## Intent

Sprint 23 must end with one triage number per leg (`off`, `static`, `v3`) and a lay-language counterpart, each with an interval that holds up under review. Nothing in the current harness can produce that: it has no paired statistics, no repeats, no record of what configuration produced a result, no way to switch the paid judges off, and only the original (clinician-worded) vignettes. Step 1 fixes the instrument **before** any spend and **before** graph v3 is designed, so the instrument cannot be shaped to flatter v3. Cost of step 1: no paid LLM calls.

## Goals

1. Compare two legs on the same vignettes with a paired test and an interval (McNemar exact + paired bootstrap), over repeats.
2. Record, per turn, whether the graph returned a match (`graph_context_matched`), in the checkpoint.
3. Let a run score severity in code only, with both LLM judges off.
4. Pin and persist the run configuration (model, provider, temperature, prompt hash) and refuse to mix configurations in one checkpoint.
5. Add a frozen lay-language version of the 27 checklists, same cases and gold labels, different wording, with a way to mark cases whose lay version can no longer support the gold label.
6. Prove the whole path end to end with zero paid-provider calls.

## Non-goals and anti-goals

- No real paid run, pilot or otherwise (steps 5 and 6). No graph v3 work (steps 3 and 4). No spend cap, circuit breaker or retry policy (step 2).
- No new dependency. `scipy`, `numpy` and `statsmodels` are not in `backend/requirements.txt`; the stats module is stdlib-only.
- No change to the existing original-set checklists or to how existing result files are read. Existing `checkpoint.jsonl` lines (no variant, no repeat) must keep loading.
- Anti-goal: a lay set written after seeing v3's vocabulary, or edited after freeze. The lay files are frozen by the commit that adds them; later edits are a new sprint decision.
- Anti-goal: a stats function that returns a confident-looking interval from too few data points. It must fail loudly (see Contracts).
- Out of scope, noted: persisting full transcripts in the checkpoint (useful for auditing under-triage cases, not requested; raise it with the sprint owner before the paid pilot).

## Decisions (by the sprint owner, 2026-11-07)

- Stats are **stdlib-only** (chosen to avoid adding a dependency).
- The other four open questions were delegated to the builder's judgement. They are listed under "Calls made" and marked as such.

## Design

### Layout (Dependency Rule)

Inner to outer, following the existing package:

- `domain.py` (entities): `Vignette` gains `pairing_exclusion: str | None = None`. `ConversationTurn` already carries `graph_context_matched`.
- `paired_stats.py` (new, pure functions, no I/O, no vendor imports): `mcnemar_exact`, `paired_bootstrap_diff`, and a small result dataclass.
- `ablation.py` (use case): the checkpoint entry key and shape change; judges become optional; repeats loop.
- `vignette_loader.py` (adapter): a `variant` argument selecting the checklist directory.
- `run_manifest.py` (new, small): builds, writes and checks the manifest. Takes plain values, not vendor objects.
- `cli.py` (Main): the only file that reads model names, temperatures and prompt text from the concrete adapters and passes them in; owns the new flags and the `compare-legs` subcommand.

### 1. Paired comparison

Unit of analysis is the **vignette**. With repeats, each vignette has per-leg under-triage and correctness as a proportion over its repeats.

- **Paired bootstrap (primary):** resample vignettes with replacement, take the difference in mean under-triage rate between leg A and leg B, 10,000 resamples, percentile 95% interval. Seeded `random.Random`, seed recorded in the manifest and in the output. Same for accuracy (the counter-metric).
- **McNemar exact (secondary):** on the vignette-level binary outcome "under-triaged in more than half of repeats". A tie (exactly half) counts as under-triaged, the conservative direction for a safety metric. Report the number of discordant pairs on each side and the exact two-sided p-value from `math.comb`.
- Only vignettes present in **both** legs and not excluded (below) enter a comparison. The output always states n.

### 2. Repeats and checkpoint shape

- New `--repeats N` (default 1).
- Checkpoint key becomes `(variant, provider, case_id, repeat)`. Old lines are read as `variant="original"`, `repeat=0`.
- Each entry additionally stores `variant`, `repeat`, and `graph_context_matched` as the list of per-turn booleans, taken from the transcript the runner already builds.
- `CheckpointStore.done` and `has()` take the full key. Resume behaviour is unchanged: a rerun skips completed keys.

### 3. Judges off

- `--no-judges` on `run-ablation`. Default is judges **on**, so existing invocations behave as before.
- `run_leg` accepts `feature_judge` and `rubric_judge` as optional. When absent, coverage and gain are not computed and are stored as `null`, never as zero (a zero would pollute later averages). `rows_for` and the results writer tolerate `null`.
- `cli.py` does not construct the DeepEval judges when the flag is set, so no judge model credentials are needed either.

### 4. Run manifest

- Written next to the checkpoint as `<checkpoint>.manifest.json`, **before the first LLM call**, so a crashed run still has one.
- Contents: system model name and temperature, simulator model name and temperature, providers list, variant, repeats, judges on/off, bootstrap seed, a sha256 of the system prompt text and of the simulator prompt text, a sha256 of the checklist directory contents (sorted file names plus bytes), harness git commit, UTC start time.
- Values are **read from the live adapters in `cli.py`** (for example `GroqClient.model_name`), not retyped, so the manifest cannot drift from what actually ran.
- On resume, the new manifest's configuration fields (everything except start time) must equal the stored one; otherwise the run stops with a message naming the differing fields. This is what stops a checkpoint from silently mixing two prompts or two models.

### 5. Lay-language set

- Directory `backend/scripts/symptom_eval/checklists_lay/<case_id>.json`, identical schema to `checklists/`. Only `opening_message`, each `first_person_phrasing`, and `update_message` differ from the original; `feature_id`, `category`, `reveal_only_if_asked` and the case id are copied unchanged.
- Optional top-level key `"excluded_from_pairing": "<reason>"`. When present, the loader sets `Vignette.pairing_exclusion`. Excluded cases still run (descriptive results stay complete) but are dropped from any comparison involving the lay set. Comparisons within the original set use all 27.
- `--variant original|lay` on `run-ablation` (default `original`). `load_all_vignettes(variant=...)` picks the directory. Gold labels always come from the raw vignette file, never from the lay file.
- Authoring: the sprint owner's assistant drafts all 27 by hand (no LLM extractor call); the sprint owner clinically reviews each; the reviewed set is committed once and then frozen. Each lay file keeps the clinical content of its original: no symptom added, none removed, no change to severity cues.

### 6. Dry run

- Goal: exercise CLI → loader → runner → checkpoint → manifest → `compare-legs` on all 27 vignettes of both variants with **zero** paid-provider calls.
- The dry run fails if any real provider client is constructed (a guard in `cli.py` behind a `--dry-run` flag, or an equivalent harness test). The Sprint 22 mock (`backend/scripts/load/mock_provider.py`) is the intended stand-in for the system under test if `GroqClient` can be pointed at it; if it cannot without changing production code, an in-process fake system is used instead and that is recorded in the plan.
- The dry run runs with `--no-judges` and `--repeats 2`, resumes once mid-way (kill and rerun), and finishes by printing a paired comparison, proving resume, repeats and stats together.

### `compare-legs`

`python -m scripts.symptom_eval.cli compare-legs --checkpoint P --variant lay --a off --b static` reads a checkpoint and prints, for under-triage and accuracy: n, per-leg rates, the difference, the bootstrap interval, the McNemar counts and p-value. Read-only, no LLM.

## Contracts (fail loudly)

- `mcnemar_exact` and `paired_bootstrap_diff` raise `ValueError` on: empty input, unequal-length inputs, fewer than 2 pairs. They never return a number for data that cannot support one.
- `CheckpointStore` raises on a line that has a `variant` or `repeat` but an unknown shape, rather than skipping it.
- Manifest mismatch on resume is an error, not a warning.

## Testing

One runnable check per piece of non-trivial logic, pytest, no network:

- `paired_stats`: McNemar against hand-computed values (for example 7 vs 1 discordant pairs → exact p = 0.0703125); bootstrap on a constructed case where the true difference is known and the seed makes the interval reproducible; all `ValueError` paths.
- Checkpoint: old-format line loads as `original`/repeat 0; new key resume skips only the matching repeat; `graph_context_matched` round-trips.
- Judges off: `null` coverage and gain survive write, reload and `rows_for`.
- Manifest: written before the first call; changed prompt hash on resume stops the run; unchanged resumes.
- Loader: `variant="lay"` reads the lay directory; `excluded_from_pairing` reaches `Vignette.pairing_exclusion`; a lay file whose `feature_id` set differs from its original fails a consistency test (this test also guards the frozen set).
- The dry run is the integration check.

## Calls made (builder's judgement, not the sprint owner's)

1. Lay set lives in a parallel directory with the same schema, not as fields inside the original files, so the original files stay untouched and the freeze is one directory.
2. Exclusion marker is a key in the lay file, so the reason travels with the case.
3. `--no-judges` defaults to judges on, to keep every existing invocation unchanged; the paid run must pass the flag explicitly.
4. Manifest sits beside the checkpoint and is enforced on resume, because a checkpoint, not a results file, is what represents one run.
5. Unit of analysis is the vignette; McNemar ties go to "under-triaged".
6. Bootstrap uses 10,000 resamples and a 95% percentile interval; seed fixed in the manifest.
7. Transcripts are not persisted (see Non-goals).

## Left to the builder

- Exact function and dataclass names, and test file layout, following existing conventions.
- How `cli.py` obtains the system and simulator prompt text for hashing without changing `LLMAgent`; if it needs a small accessor on `LLMAgent`, that is allowed and listed in the plan.
- Whether `GroqClient` can be pointed at the Sprint 22 mock without production code changes (decides the dry-run mechanism).

## Skills applied

- **clean-architecture:** stats and manifest logic are pure and import no vendor SDK; `cli.py` stays the only composition root; judges stay behind their existing ports and become optional rather than faked.
- **pragmatic-programmer:** manifest reads values from the objects that use them (DRY); dry run is the tracer bullet through every new piece; contracts fail early on bad statistical input.
- **clean-code:** `null` for not-computed instead of a misleading `0`; a flag argument on `run_leg` avoided by passing the judges as optional collaborators.
