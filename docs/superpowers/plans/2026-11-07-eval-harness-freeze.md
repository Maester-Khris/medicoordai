# Eval Harness Freeze Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the symptom-eval harness produce paired, repeat-aware, reproducible triage comparisons (original and lay-language vignettes) at zero LLM spend.

**Architecture:** Pure stats and manifest modules inside `backend/scripts/symptom_eval/`; the checkpoint grows a `(variant, provider, case_id, repeat)` key; judges become optional collaborators; `cli.py` stays the only composition root. A dry run with in-process fakes proves the whole path.

**Tech Stack:** Python 3.11, stdlib only (`math`, `random`, `hashlib`, `json`), pytest.

**Spec:** `docs/superpowers/specs/2026-11-07-eval-harness-freeze-design.md` (approved 2026-11-07)

## Global Constraints

- No new dependency. `scipy`, `numpy`, `statsmodels` are not in `backend/requirements.txt`; stats are stdlib-only.
- Severity values are exactly `routine | moderate | urgent | emergent`.
- Old `results/checkpoint.jsonl` lines (no `variant`, no `repeat`) must keep loading as `variant="original"`, `repeat=0`.
- Gold labels always come from the raw vignette file, never from a lay checklist.
- Lay files are frozen once committed; edits after that are a new sprint decision.
- Run every command with `source /home/niki/Documents/workenv/pydev/bin/activate` and from `backend/`. Tests here need no secrets, so no `doppler run --`.
- Commits: conventional, one line, no body, no AI attribution or co-author line (user's global rule overrides any default). Ask for approval before each commit. One commit per task.
- The spec and this plan are committed together, once, before Task 1.

## Deviations from the spec (decided while planning)

1. The manifest resume check compares every configuration field **except** `providers`, `harness_git_commit` and `started_at`. A new leg added to an existing checkpoint is not a mixed configuration, and the git commit changes between sessions, so including either would block legitimate resumes.
2. The automated dry run uses in-process fakes, not the Sprint 22 mock. It is deterministic and runs in pytest. A manual smoke against the mock via `GROQ_BASE_URL` is an optional step in Task 9, not a gate.
3. `compare-legs` also reports how many conversations ended unclassified per leg (see Review Focus 2).

## Review Focus

1. A checkpoint line that is truncated or malformed (crash mid-write) must stop the load with the line number, not be skipped. Pinned in Task 1.
2. A conversation that never classifies (`final_severity=None`) is not "under-triaged", so a leg that never answers looks safe. The comparison must report unclassified counts beside the rates. Pinned in Task 5.
3. Zero discordant pairs: McNemar returns p = 1.0 and bootstrap on identical vectors returns a zero-width interval; neither divides by zero. Pinned in Task 4.
4. Legs covering different vignettes (partial run): compare only the intersection, print n, and raise if fewer than 2 remain. Pinned in Task 5.
5. A lay run must not skip work already done in the original run, and vice versa (same provider and case id, different variant). Pinned in Task 1.

## File Structure

- Modify `backend/scripts/symptom_eval/ablation.py`: checkpoint key and shape, repeats, optional judges.
- Create `backend/scripts/symptom_eval/paired_stats.py`: McNemar exact and paired bootstrap.
- Create `backend/scripts/symptom_eval/compare_legs.py`: checkpoint to per-vignette rates to comparison report.
- Create `backend/scripts/symptom_eval/run_manifest.py`: manifest build, write, resume check.
- Modify `backend/scripts/symptom_eval/domain.py`, `vignette_loader.py`: `pairing_exclusion`, `variant`.
- Create `backend/scripts/symptom_eval/checklists_lay/<case_id>.json` (27 files).
- Create `backend/scripts/symptom_eval/dry_run.py`: deterministic fake system and simulator.
- Modify `backend/scripts/symptom_eval/cli.py`, `system_under_test.py`, `patient_simulator.py`: flags, wiring, two small accessors.
- Tests in `backend/scripts/symptom_eval/tests/`, one file per new module.

---

### Task 1: Checkpoint key, repeats, per-turn graph flags

**Files:**
- Modify: `backend/scripts/symptom_eval/ablation.py`
- Modify (call sites): `backend/scripts/symptom_eval/tests/test_ablation.py`

**Interfaces:**
- Produces:
  - `CheckpointStore.has(variant: str, provider: str, case_id: str, repeat: int) -> bool`
  - `CheckpointStore.append(variant: str, provider: str, repeat: int, confusion_row: ConfusionMatrixRow, coverage: ElicitationCoverageResult | None, gain: InformationGainResult | None, graph_context_matched: list[bool]) -> None`
  - `CheckpointStore.entries_for(variant: str, provider: str) -> list[dict]`
  - `CheckpointStore.rows_for(variant: str, provider: str) -> tuple[list[ConfusionMatrixRow], list[ElicitationCoverageResult | None], list[InformationGainResult | None]]`
  - `run_leg(provider, vignettes, system_factory, simulator, feature_judge, rubric_judge, checkpoint=None, variant: str = "original", repeats: int = 1) -> AblationLegResult`; `run_ablation` gains the same `variant` and `repeats`.

- [ ] **Step 1: Write failing tests** in `test_ablation.py` (update the three existing `has`/`rows_for` call sites to the new signatures first):
  - `test_old_format_line_loads_as_original_repeat_zero`: write a JSONL line without `variant`/`repeat`; `has("original", "off", "1", 0)` is True.
  - `test_variants_do_not_skip_each_other` (Review Focus 5): complete `("original","off","1",0)`; `has("lay","off","1",0)` is False.
  - `test_resume_skips_only_matching_repeat`: with `repeats=2`, run, then a counting system on resume makes 0 calls; with a checkpoint holding only repeat 0, resume makes calls for repeat 1 only.
  - `test_graph_context_matched_roundtrips`: a fake system returning `graph_context_matched=True` yields `entries_for(...)[0]["graph_context_matched"] == [True]` after reload.
  - `test_truncated_line_raises_with_line_number` (Review Focus 1): file whose second line is `{"provider": "off"`; constructing `CheckpointStore` raises `ValueError` whose message contains `line 2`.
- [ ] **Step 2: Run to verify fail:** `pytest scripts/symptom_eval/tests/test_ablation.py -v` → FAIL (signature/key errors).
- [ ] **Step 3: Implement** the interfaces above in `ablation.py`. Entry dict gains `variant`, `repeat`, `graph_context_matched`. Loader defaults missing `variant` to `"original"` and missing `repeat` to `0`. `run_leg` loops `for repeat in range(repeats)` inside the vignette loop, skipping completed keys, and passes `[t.graph_context_matched for t in transcript.turns]`.
- [ ] **Step 4: Run to verify pass:** same command → all PASS, plus the full folder: `pytest scripts/symptom_eval -q`.
- [ ] **Step 5: Commit** (after approval): `git add backend/scripts/symptom_eval/ablation.py backend/scripts/symptom_eval/tests/test_ablation.py` · `feat(eval): key the checkpoint by variant and repeat and persist per-turn graph matches`

### Task 2: Optional judges, `null` for not computed

**Files:**
- Modify: `backend/scripts/symptom_eval/ablation.py`
- Test: `backend/scripts/symptom_eval/tests/test_ablation.py`

**Interfaces:**
- Consumes: Task 1 signatures.
- Produces: `run_leg` and `run_ablation` accept `feature_judge: FeaturePresenceJudgePort | None` and `rubric_judge: RubricJudgePort | None`; `AblationLegResult.elicitation_coverage` and `.information_gain` are `list[... | None]`.

- [ ] **Step 1: Failing tests:** `test_no_judges_stores_null_and_never_calls_scoring` (pass `None` for both; entry has `"coverage": None` and `"gain": None`; severity row still scored); `test_null_scores_survive_reload` (`rows_for` returns `None` entries in the coverage and gain lists); `test_one_judge_off_other_on` (only the supplied judge's result is non-null).
- [ ] **Step 2:** run → FAIL.
- [ ] **Step 3:** In `run_leg`, call `elicitation_coverage.score_vignette` / `information_gain.score_vignette` only when the judge is not `None`; otherwise the value is `None`. `CheckpointStore.append` writes `null`; `rows_for` rebuilds a result only when the stored value is not `None`.
- [ ] **Step 4:** run → PASS; then `pytest scripts/symptom_eval -q`.
- [ ] **Step 5: Commit:** `git add backend/scripts/symptom_eval/ablation.py backend/scripts/symptom_eval/tests/test_ablation.py` · `feat(eval): let a run skip both LLM judges and store null scores`

### Task 3: Run manifest

**Files:**
- Create: `backend/scripts/symptom_eval/run_manifest.py`
- Test: `backend/scripts/symptom_eval/tests/test_run_manifest.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) RunManifest` with fields `system_model: str, system_temperature: float, simulator_model: str, simulator_temperature: float, providers: tuple[str, ...], variant: str, repeats: int, judges_enabled: bool, bootstrap_seed: int, system_prompt_sha256: str, simulator_prompt_sha256: str, checklists_sha256: str, harness_git_commit: str`
  - `sha256_text(text: str) -> str`; `hash_directory(path: str) -> str` (sorted file names plus bytes)
  - `manifest_path(checkpoint_path: str) -> str` → `f"{checkpoint_path}.manifest.json"`
  - `write_or_verify_manifest(checkpoint_path: str, manifest: RunManifest, started_at: str) -> None`
  - `class ManifestMismatch(Exception)`

- [ ] **Step 1: Failing tests:** `test_first_call_writes_manifest_file`; `test_same_config_resumes` (second call with a new `started_at` and different `providers` and `harness_git_commit` does not raise, per Deviation 1); `test_changed_prompt_hash_raises_naming_field` (message contains `system_prompt_sha256`); `test_changed_repeats_raises`; `test_hash_directory_changes_when_a_file_changes`; `test_hash_directory_is_order_independent_of_creation`.
- [ ] **Step 2:** run `pytest scripts/symptom_eval/tests/test_run_manifest.py -v` → FAIL (module missing).
- [ ] **Step 3:** Implement. Equality ignores `providers`, `harness_git_commit` and `started_at`; `ManifestMismatch` lists every differing field name with old and new value.
- [ ] **Step 4:** run → PASS.
- [ ] **Step 5: Commit:** `git add backend/scripts/symptom_eval/run_manifest.py backend/scripts/symptom_eval/tests/test_run_manifest.py` · `feat(eval): add a run manifest that stops a checkpoint mixing configurations`

### Task 4: Paired statistics

**Files:**
- Create: `backend/scripts/symptom_eval/paired_stats.py`
- Test: `backend/scripts/symptom_eval/tests/test_paired_stats.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) McNemarResult: only_a: int; only_b: int; p_value: float`
  - `@dataclass(frozen=True) BootstrapResult: diff: float; low: float; high: float; resamples: int; seed: int`
  - `mcnemar_exact(a: Sequence[bool], b: Sequence[bool]) -> McNemarResult` (`True` = event; `only_a` = a True and b False)
  - `paired_bootstrap_diff(a: Sequence[float], b: Sequence[float], seed: int, resamples: int = 10_000) -> BootstrapResult` (`diff = mean(a) - mean(b)`, 95% percentile interval)

- [ ] **Step 1: Failing tests:** `test_mcnemar_7_vs_1_is_0_0703125` (7 only-a, 1 only-b → `p_value == 0.0703125`); `test_mcnemar_zero_discordant_is_one` (Review Focus 3); `test_mcnemar_counts_ignore_concordant_pairs`; `test_bootstrap_known_difference` (a all 1.0, b all 0.0 → `diff == 1.0`, `low == high == 1.0`); `test_bootstrap_identical_vectors_zero_width` (Review Focus 3); `test_bootstrap_reproducible_with_seed` (same seed → equal results, different seed → may differ); `test_raises_value_error_on_empty_unequal_or_single_pair` (all three input kinds, both functions).
- [ ] **Step 2:** run → FAIL.
- [ ] **Step 3:** Implement stdlib-only. McNemar: two-sided exact binomial with `p = 0.5` over `n = only_a + only_b`, `min(1.0, 2 * P(X <= min(only_a, only_b)))`, via `math.comb`. Bootstrap: `random.Random(seed)`, resample indices with replacement, percentile bounds at 2.5 and 97.5.
- [ ] **Step 4:** run → PASS.
- [ ] **Step 5: Commit:** `git add backend/scripts/symptom_eval/paired_stats.py backend/scripts/symptom_eval/tests/test_paired_stats.py` · `feat(eval): add exact McNemar and paired bootstrap statistics`

### Task 5: Leg comparison from a checkpoint

**Files:**
- Create: `backend/scripts/symptom_eval/compare_legs.py`
- Test: `backend/scripts/symptom_eval/tests/test_compare_legs.py`

**Interfaces:**
- Consumes: `CheckpointStore.entries_for` (Task 1), `mcnemar_exact`, `paired_bootstrap_diff` (Task 4).
- Produces:
  - `@dataclass(frozen=True) MetricComparison: rate_a: float; rate_b: float; bootstrap: BootstrapResult; mcnemar: McNemarResult | None`
  - `@dataclass(frozen=True) LegComparison: variant: str; leg_a: str; leg_b: str; n: int; under_triage: MetricComparison; accuracy: MetricComparison; unclassified_a: int; unclassified_b: int`
  - `compare_legs(checkpoint: CheckpointStore, variant: str, leg_a: str, leg_b: str, excluded_case_ids: frozenset[str], seed: int) -> LegComparison`
  - `format_comparison(c: LegComparison) -> str`

- [ ] **Step 1: Failing tests** (build the checkpoint with `CheckpointStore.append` in a tmp dir):
  - `test_per_vignette_rate_is_mean_over_repeats`.
  - `test_mcnemar_tie_counts_as_under_triaged` (rate exactly 0.5 → event).
  - `test_excluded_cases_are_dropped_and_n_reported`.
  - `test_only_intersection_of_vignettes_is_compared` (Review Focus 4) and `test_fewer_than_two_shared_vignettes_raises`.
  - `test_unclassified_counted_separately_and_not_under_triaged` (Review Focus 2): rows with `predicted=None` raise `unclassified_a`, leave `under_triage` unchanged.
  - `test_format_comparison_states_n_rates_interval_and_counts` (string contains `n=`, both rates, the interval, `unclassified`).
- [ ] **Step 2:** run → FAIL.
- [ ] **Step 3:** Implement. Under-triage and accuracy rate per vignette = mean of `under_triaged` / `correct` over that vignette's repeats; McNemar only for under-triage using `rate >= 0.5`. `unclassified_*` counts entries with `predicted is None`.
- [ ] **Step 4:** run → PASS.
- [ ] **Step 5: Commit:** `git add backend/scripts/symptom_eval/compare_legs.py backend/scripts/symptom_eval/tests/test_compare_legs.py` · `feat(eval): compare two checkpoint legs with paired intervals`

### Task 6: Lay variant support in the loader

**Files:**
- Modify: `backend/scripts/symptom_eval/domain.py`, `backend/scripts/symptom_eval/vignette_loader.py`
- Test: `backend/scripts/symptom_eval/tests/test_vignette_loader.py`, create `backend/scripts/symptom_eval/tests/test_lay_checklists.py`

**Interfaces:**
- Produces:
  - `Vignette.pairing_exclusion: str | None = None` (last field, defaulted)
  - `CHECKLISTS_LAY_DIR: str`; `checklists_dir_for(variant: str) -> str` (`ValueError` on anything but `"original"` / `"lay"`)
  - `load_all_vignettes(raw_path=RAW_VIGNETTES_PATH, checklists_dir: str | None = None, variant: str = "original") -> list[Vignette]` (`checklists_dir` wins when given)

- [ ] **Step 1: Failing tests:** `test_excluded_from_pairing_reaches_vignette` (checklist with `"excluded_from_pairing": "lay wording drops the stridor cue"` → `pairing_exclusion` equals that string); `test_missing_key_means_none`; `test_variant_lay_reads_lay_dir`; `test_unknown_variant_raises`. In `test_lay_checklists.py`: `test_lay_checklists_match_originals` loops every file in `checklists_lay/` and asserts the same top-level keys (plus optional `excluded_from_pairing`), same case id as an original, and equal ordered `(feature_id, category, reveal_only_if_asked)` triples. It passes vacuously while the directory is empty.
- [ ] **Step 2:** run → FAIL.
- [ ] **Step 3:** Implement; create `checklists_lay/.gitkeep`.
- [ ] **Step 4:** run → PASS; `pytest scripts/symptom_eval -q`.
- [ ] **Step 5: Commit:** `git add backend/scripts/symptom_eval/domain.py backend/scripts/symptom_eval/vignette_loader.py backend/scripts/symptom_eval/checklists_lay/.gitkeep backend/scripts/symptom_eval/tests/test_vignette_loader.py backend/scripts/symptom_eval/tests/test_lay_checklists.py` · `feat(eval): load the lay-language checklist variant with a pairing exclusion marker`

### Task 7: Author the 27 lay-language checklists

**Files:**
- Create: `backend/scripts/symptom_eval/checklists_lay/<case_id>.json` ×27 (ids as in `checklists/`)
- Test: `backend/scripts/symptom_eval/tests/test_lay_checklists.py`

**Interfaces:**
- Consumes: Task 6 loader and consistency test.

- [ ] **Step 1: Failing test** `test_every_original_has_a_lay_version` (set of lay file names equals set of original file names) → FAIL (empty directory).
- [ ] **Step 2: Author by hand, no LLM extractor.** For each original, keep `feature_id`, `category`, `reveal_only_if_asked` and item order; rewrite only `opening_message`, each `first_person_phrasing` and `update_message` in how a layperson would say it ("syncope" → "passed out", no clinical terms the original does not already put in a patient's mouth). Add no symptom, remove none, change no severity cue. If a rewrite loses a cue the gold label depends on, keep the closest honest wording and add `"excluded_from_pairing": "<reason>"`.
- [ ] **Step 3:** run `pytest scripts/symptom_eval/tests/test_lay_checklists.py -v` → PASS.
- [ ] **Step 4: Review gate:** the sprint owner reads all 27 diffs line by line for clinical meaning. Do not commit until they approve; any change they request is made before the commit (the set freezes at the commit).
- [ ] **Step 5: Commit:** `git add backend/scripts/symptom_eval/checklists_lay backend/scripts/symptom_eval/tests/test_lay_checklists.py` · `feat(eval): add the frozen lay-language versions of the 27 checklists`

### Task 8: CLI wiring (flags, manifest, `compare-legs`)

**Files:**
- Modify: `backend/scripts/symptom_eval/cli.py`, `system_under_test.py`, `patient_simulator.py`
- Test: `backend/scripts/symptom_eval/tests/test_cli.py`

**Interfaces:**
- Consumes: Tasks 1 to 6.
- Produces:
  - `run-ablation` flags `--variant {original,lay}`, `--repeats N` (default 1), `--no-judges`, `--seed N` (default `BOOTSTRAP_SEED = 20261107`); subcommand `compare-legs --checkpoint P --variant V --a LEG --b LEG`.
  - `build_judges(enabled: bool) -> tuple[FeaturePresenceJudgePort | None, RubricJudgePort | None]` in `cli.py`.
  - `patient_simulator.SIMULATOR_TEMPERATURE: float = 0.3`, used by `reply` (replaces the literal).
  - `LiveLLMAgentAdapter.model_name` property (adapter keeps its `GroqClient` as `self._client`).

- [ ] **Step 1: Failing tests:** `test_build_judges_disabled_returns_none_without_constructing` (monkeypatch both DeepEval constructors to raise; `build_judges(False) == (None, None)`); `test_results_writer_handles_null_scores` (a leg with `None` coverage and gain serialises); `test_manifest_written_before_first_system_call` (fake system records whether `manifest_path(checkpoint)` already exists when `respond` is first called); `test_compare_legs_command_prints_comparison` (checkpoint built by Task 1 API in tmp; capture stdout).
- [ ] **Step 2:** run → FAIL.
- [ ] **Step 3: Implement.** Build the `RunManifest` in `cli.py` from the live objects: models via `model_name` (check `backend/llm/base.py` for the simulator client's equivalent and read it the same way); system prompt hash over `build_system_prompt(<LLMAgent max followups>)` from `llm.prompts` (if only a private attribute holds the value, add a read-only `max_followups` property on `LLMAgent` and list it in the commit); simulator prompt hash over `SIMULATOR_SYSTEM_PROMPT`; system temperature taken from where `LLMAgent` calls `chat` (if it passes none, read the default via `inspect.signature(GroqClient.chat).parameters["temperature"].default`); checklists hash via `hash_directory(checklists_dir_for(variant))`; git commit via `git rev-parse HEAD`. Call `write_or_verify_manifest` before `run_ablation`. `compare-legs` builds `excluded_case_ids` from `load_all_vignettes(variant=...)` entries with a `pairing_exclusion`, and none for `original`. Make the results writer emit `None` for null scores.
- [ ] **Step 4:** run `pytest scripts/symptom_eval -q` → PASS.
- [ ] **Step 5: Commit:** `git add backend/scripts/symptom_eval/cli.py backend/scripts/symptom_eval/system_under_test.py backend/scripts/symptom_eval/patient_simulator.py backend/scripts/symptom_eval/tests/test_cli.py` (plus `backend/services/llm_agent.py` only if the accessor was needed) · `feat(eval): wire variant, repeats, no-judges, manifest and compare-legs into the CLI`

### Task 9: Dry run

**Files:**
- Create: `backend/scripts/symptom_eval/dry_run.py`
- Modify: `backend/scripts/symptom_eval/cli.py` (`--dry-run`)
- Test: `backend/scripts/symptom_eval/tests/test_dry_run.py`

**Interfaces:**
- Produces: `FakeSystem` and `FakeSimulator` (deterministic: severity = `SEVERITIES[sha1(provider + first_patient_message) % 4]`, never calls a network); `run-ablation --dry-run` uses them, prefixes all output with `DRY RUN`, and writes to a temp checkpoint unless `--checkpoint` is given.

- [ ] **Step 1: Failing test** `test_dry_run_end_to_end_with_resume_and_zero_provider_calls`: monkeypatch `GroqClient.__init__` and `AnthropicClient.__init__` to raise; run `run_ablation_command(variant="original", repeats=2, judges=False, providers=("off","static"), dry_run=True, checkpoint=tmp)` with a fake that raises a sentinel exception after N system calls; assert the checkpoint holds partial entries; rerun and assert completed keys were not recomputed (call counter) and the final checkpoint has `27 × 2 legs × 2 repeats` entries; then `compare_legs` returns `n == 27`. Repeat the same for `variant="lay"`.
- [ ] **Step 2:** run → FAIL.
- [ ] **Step 3:** Implement `dry_run.py` and the flag.
- [ ] **Step 4:** run `pytest scripts/symptom_eval -q` → PASS.
- [ ] **Step 5 (optional, not a gate):** manual smoke of the system leg against the Sprint 22 mock: start `backend/scripts/load/mock_provider.py`, set `GROQ_BASE_URL` to it, run one vignette with `--no-judges`. Note in the task summary whether `GroqClient` reaches the mock; if it does not, nothing changes.
- [ ] **Step 6: Commit:** `git add backend/scripts/symptom_eval/dry_run.py backend/scripts/symptom_eval/cli.py backend/scripts/symptom_eval/tests/test_dry_run.py` · `test(eval): add a zero-spend dry run covering resume, repeats and comparison`

### Task 10: Persist full transcripts (follow-on; do before the paid pilot, step 5)

Recorded in the sprint 23 memory notes: transcripts let individual under-triage cases be audited after a run you cannot cheaply repeat. The spec lists it as a non-goal **for step 1**; this task is deliberately last, outside the step 1 deliverable, and needs the sprint owner's go-ahead at that point.

**Files:**
- Modify: `backend/scripts/symptom_eval/ablation.py`
- Test: `backend/scripts/symptom_eval/tests/test_ablation.py`

**Interfaces:**
- Consumes: Task 1 `append`.
- Produces: `append(..., transcript: list[dict])` where each dict is `{"turn_index", "patient_message", "system_response", "graph_context_matched"}`; entries gain a `transcript` key; old lines without it still load (`entries_for` returns them without the key).

- [ ] **Step 1: Failing tests:** `test_transcript_roundtrips`; `test_entry_without_transcript_still_loads`.
- [ ] **Step 2:** run → FAIL.
- [ ] **Step 3:** Implement; `run_leg` builds the list from `transcript.turns`.
- [ ] **Step 4:** run `pytest scripts/symptom_eval -q` → PASS.
- [ ] **Step 5: Commit:** `git add backend/scripts/symptom_eval/ablation.py backend/scripts/symptom_eval/tests/test_ablation.py` · `feat(eval): persist full conversation transcripts in the checkpoint`

---

## Self-review

- **Spec coverage:** paired comparison (Tasks 4, 5), repeats (1), `graph_context_matched` (1), judges off (2), manifest and resume check (3, 8), lay set and exclusion (6, 7), `--variant` (6, 8), `compare-legs` (5, 8), dry run (9), contracts that fail loudly (1, 3, 4, 5). Transcripts are Task 10.
- **Types:** `variant`, `repeat`, `entries_for`, `rows_for` and `CheckpointStore.append` are used with identical signatures in Tasks 2, 5, 8, 9, 10.
- **Skills applied:** clean-architecture (stats, manifest and compare stay vendor-free; `cli.py` is the only place reading adapters), pragmatic-programmer (manifest values read from live objects; Task 9 is the tracer through every piece), clean-code (`None` rather than `0` for not computed; judges as optional collaborators instead of a flag argument inside `run_leg`), test-driven-development (every code task starts with a failing test).
