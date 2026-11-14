# Graph v3 and Semantic Retrieval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the SNOMED/CTAS Neo4j graph on a bounded, lay-aware footing and add a feature-flagged semantic candidate path (ONNX int8 embeddings, in-process vectors) that falls back to today's lexical lookup.

**Architecture:** An offline/deploy-time build writes Layer 1 (anchors, depth-1 concepts, English descriptions, reviewed lay phrases) and Layer 2 into Neo4j, then derives a versioned vector artifact (matrix + manifest) on the python-api volume. At request time `Neo4jSemanticProvider` adds semantic candidates to the existing candidate step (lexical exact hits outrank), behind a deadline, breaker and bounded worker pool; the existing IS_A traversal, red-flag collection and `GraphContext` contract are unchanged.

**Tech Stack:** Python 3.11, FastAPI, Neo4j (AuraDB Free), onnxruntime + tokenizers (runtime), numpy, torch/optimum only in the offline export tool, pytest.

**Spec:** `docs/superpowers/specs/2026-11-08-graph-v3-semantic-retrieval-design.md` (approved 2026-11-08). Offline harness: `backend/scripts/embedding_eval/`.

## Global Constraints

- English only. Provider value `neo4j_semantic`; `off` stays the default; `neo4j` (v2) and `static` behave exactly as before.
- `GraphContextProvider.get_symptom_graph_context` never raises; any semantic failure degrades to the lexical result, then to `matched=False`.
- Severity values are exactly `routine | moderate | urgent | emergent`; severity classification stays the LLM's job.
- Runtime imports onnxruntime and tokenizers, never torch. New packages (`onnxruntime`, `tokenizers`, and a direct `numpy` pin) go into `backend/requirements.txt` and are named in the task summary.
- Model names, paths and tunables come from env vars (`SEMANTIC_MODEL_DIR`, `SEMANTIC_INDEX_DIR`, `EMBED_THREADS` default `1`, `EMBED_DEADLINE_MS` default `250`, `SEMANTIC_LAY_RULE`), never hard-coded; secrets never printed or logged; Neo4j credentials from env (`NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD`), never CLI arguments.
- Starting budgets (approved, unsourced): p95 added latency ≤ 120 ms; single-box capacity ≥ 15 turns/s; out-of-scope false-match rate ≤ 5%; hit@5 lower 95% bound ≥ 75% on the independent valid set.
- Python: `source /home/niki/Documents/workenv/pydev/bin/activate`; tests from `backend/` with `doppler run -- pytest ...`; live-Neo4j tests carry `@pytest.mark.integration`.
- Paid LLM calls need the user's go-ahead with the cost estimate first. Commits: conventional, one line, no body, no AI attribution, one approval per commit. The spec and this plan are committed together, once, before Task 1.

## Review Focus

1. A wipe must never run against the wrong instance: `build_graph_v3 --wipe` refuses without `--confirm-wipe <instance id>` matching `AURA_INSTANCE_ID`. (Task 7)
2. A stale or half-written index must never be loaded: manifest mismatch or a crash mid-build leaves the previous index (or none) and the API serves lexical-only. (Tasks 3, 4)
3. Concurrent turns while the embedder is slow must not pile up: excess turns skip the semantic path instead of queueing past the deadline. (Task 5)
4. A message with no embeddable content (empty, whitespace, emoji only) must skip the semantic path without error. (Tasks 5, 8)
5. A short lexical hit must not outrank a correct semantic hit; only lexical hits of at least `LEXICAL_PRECEDENCE_MIN_LEN` (12 characters, config) take precedence. (Task 7)

## File Structure

- Create `backend/scripts/snomed_ingest/`: `anchor_selection.py`, `lay_descriptions.py`, `import_lay_candidates.py`, `layer1_writer.py`, `graph_health.py`, `build_graph_v3.py`, `aura_snapshot.py`, `data/lay_descriptions.json`, `data/index_depth_overrides.json`.
- Modify `backend/scripts/snomed_ingest/load_rf2.py` (use the extracted writers), `seed_red_flags.py` (question scope).
- Create `backend/graph/semantic/`: `settings.py`, `embedder.py`, `index.py`, `build.py`, `candidates.py`, `abstention.py`; create `backend/graph/snomed_neo4j/semantic_provider.py`.
- Modify `backend/graph/snomed_neo4j/provider.py` (candidate seam), `backend/graph/factory.py`, `backend/main.py` (health), `backend/metrics.py`.
- Create `backend/scripts/embedding_eval/`: `export_onnx.py`, `eval_index.py`, `calibrate.py`, `bench_embedder.py`, `data/negative_queries.json`; modify `gen_queries.py`, `gen_lay_descriptions.py`.
- Modify `backend/scripts/symptom_eval/run_manifest.py`, `cli.py` (v3 leg provenance).
- Tests: `backend/tests/scripts/snomed_ingest/`, `backend/tests/graph/` (semantic tests as `test_semantic_*.py`), `backend/scripts/embedding_eval/tests/`.

Streams: Tasks 1–8 (graph build) and 9–10 (embedder) are independent until Task 12; 11–14 follow 9–10.

---

### Task 1: Anchor selection (primary anchor, depth, blocklist)

**Files:** Create `backend/scripts/snomed_ingest/anchor_selection.py`, `data/index_depth_overrides.json` (`{}` to start); Test `backend/tests/scripts/snomed_ingest/test_anchor_selection.py`

**Interfaces:**
- Produces: `@dataclass(frozen=True) AnchorSpec(anchor_id: str, name: str, depth: int)`; `@dataclass(frozen=True) Assignment(concept_anchor: dict[str, str], concept_depth: dict[str, int], ties: dict[str, tuple[str, ...]], broad: tuple[str, ...])`; `assign_concepts(children: Mapping[str, Sequence[str]], anchors: Sequence[AnchorSpec]) -> Assignment`; `resolve_index_depth(name: str, anchor_id: str, overrides: Mapping[str, int]) -> int`; constants `BLOCKED_ROOTS = frozenset({"404684003", "95320005", "66091009"})`, `DEFAULT_INDEX_DEPTH = 1`, `BROAD_CONCEPT_THRESHOLD = 200`, `CATCH_ALL_NAMES = ("Other skin conditions", "Congenital problem in children", "Post-operative complications")`.

- [ ] **Step 1: Failing tests:** `test_concept_goes_to_nearest_anchor`; `test_tie_goes_to_earlier_anchor_and_is_reported_in_ties`; `test_depth_zero_returns_only_the_anchor`; `test_blocked_root_is_never_assigned_or_traversed`; `test_anchor_over_200_concepts_at_depth_two_is_flagged_broad`; `test_catch_all_names_default_to_depth_zero`; `test_override_beats_default`.
- [ ] **Step 2:** Run `doppler run -- pytest backend/tests/scripts/snomed_ingest/test_anchor_selection.py -v`. Expected: FAIL (module missing).
- [ ] **Step 3:** Implement per the signatures: BFS downward per anchor to its depth; nearest anchor wins; ties go to the anchor listed first and are recorded; `broad` is computed on the depth-2 closure size regardless of the applied depth.
- [ ] **Step 4:** Rerun. Expected: PASS.
- [ ] **Step 5: Commit** `git add backend/scripts/snomed_ingest/anchor_selection.py backend/scripts/snomed_ingest/data/index_depth_overrides.json backend/tests/scripts/snomed_ingest/test_anchor_selection.py` · `feat(graph): add primary-anchor assignment with per-anchor index depth`

### Task 2: Lay-description data file, inclusion rule and import

**Files:** Create `backend/scripts/snomed_ingest/lay_descriptions.py`, `import_lay_candidates.py`, `data/lay_descriptions.json`; Test `.../test_lay_descriptions.py`

**Interfaces:**
- Produces: `@dataclass(frozen=True) LayPhrase(anchor_id: str, text: str, source: str, status: str)` with status in `generated|confirmed|rejected|approved`; `load_lay_descriptions(path: Path, valid_anchor_ids: Collection[str]) -> list[LayPhrase]`; `select_for_index(phrases: Sequence[LayPhrase], rule: str) -> list[LayPhrase]` (`all`: not rejected; `confirmed`: confirmed or approved; `approved`: approved); `lay_description_id(anchor_id: str, text: str) -> str` = `"lay:" + anchor_id + ":" + sha1(text)[:12]`. File format `{"version": 1, "phrases": [...]}`.

- [ ] **Step 1: Failing tests:** `test_loader_rejects_unknown_status_and_unknown_anchor`; `test_phrases_under_two_words_are_dropped_and_duplicates_collapsed`; `test_rule_all_excludes_rejected`; `test_rule_confirmed_includes_approved`; `test_rule_approved_is_strictest`; `test_description_id_is_stable_and_prefixed`.
- [ ] **Step 2:** Run; expect FAIL. **Step 3:** Implement. `import_lay_candidates.py` converts `scripts/embedding_eval/results/lay_description_candidates.json` into the data file (`agree_top3` → `confirmed`, else `generated`, `source` = the generating model), CLI with `--out`.
- [ ] **Step 4:** Run tests; then run the importer once to create `data/lay_descriptions.json` (1,487 phrases) and run the loader on it. Expected: PASS and 149 anchors loaded.
- [ ] **Step 5: Commit** `git add backend/scripts/snomed_ingest/lay_descriptions.py backend/scripts/snomed_ingest/import_lay_candidates.py backend/scripts/snomed_ingest/data/lay_descriptions.json backend/tests/scripts/snomed_ingest/test_lay_descriptions.py` · `feat(graph): add the reviewable lay-description data file and inclusion rules`

### Task 3: Second generation pass for anchors without a confirmed phrase (paid, about $0.02)

**Files:** Modify `backend/scripts/embedding_eval/gen_lay_descriptions.py`; Test `backend/scripts/embedding_eval/tests/test_gen_lay_weak.py`

**Interfaces:** Produces `anchors_without_confirmed(candidates: Sequence[dict], minimum: int = 1) -> list[int]` and a `--weak` CLI mode that regenerates only those anchors with the cue-preserving prompt of `gen_queries.describe(detailed=True)` style (defining facts: cause, body part, who, when).

- [ ] **Step 1: Failing tests:** `test_anchors_without_confirmed_lists_only_anchors_below_minimum`; `test_weak_mode_keeps_existing_confirmed_phrases` (pure merge function `merge_candidates(existing, regenerated)`).
- [ ] **Step 2–4:** Implement and run (unit tests). **Gate:** tell the user the estimate (about $0.02) and wait for the go-ahead before the paid run; then run `--weak`, re-run Task 2's importer, and report how many anchors still lack a confirmed phrase. The user spot-checks the emergent anchors' phrases and may set `approved`/`rejected` in the data file.
- [ ] **Step 5: Commit** `feat(graph): regenerate lay phrases for anchors without a confirmed phrase`

### Task 4: Extract Layer 1 writers and add lay-description nodes

**Files:** Create `backend/scripts/snomed_ingest/layer1_writer.py`; Modify `load_rf2.py`; Test `.../test_layer1_writer.py`, existing `test_load_rf2.py` must still pass

**Interfaces:**
- Produces: `write_constraints(session) -> None`; `write_concepts(session, rows: Iterable[dict]) -> None`; `write_descriptions(session, rows: Iterable[dict]) -> None`; `write_is_a(session, rows: Iterable[dict]) -> None`; `write_lay_descriptions(session, phrases: Sequence[LayPhrase]) -> None`; `BATCH_SIZE = 1000`. Cypher text for the first four is moved verbatim from `load_rf2.load`.
- Lay nodes: `MERGE (d:Description {id: $lay_id}) SET d.term, d.language_code = "en", d.kind = "lay", d.source, d.status, d.is_fsn = false` plus `MATCH (c:SnomedConcept {id: anchor_id}) MERGE (c)-[:HAS_DESCRIPTION]->(d)`.

- [ ] **Step 1: Failing tests (fake session recording `run` calls):** `test_load_rf2_still_issues_the_same_cypher_in_the_same_order` (snapshot of the four statements); `test_lay_writer_sets_kind_language_and_links_to_the_anchor`; `test_lay_writer_batches_at_1000`.
- [ ] **Step 2–4:** Refactor `load_rf2.load` to call the writers (no behaviour change), add the lay writer, run `doppler run -- pytest backend/tests/scripts/snomed_ingest -v`. Expected: all PASS.
- [ ] **Step 5: Commit** `refactor(graph): extract Layer 1 writers and add lay-description nodes`

### Task 5: Scope follow-up questions per anchor

**Files:** Modify `backend/scripts/snomed_ingest/seed_red_flags.py` (and the constraint step in `reseed_layer2_per_anchor.py` if it names the old constraint); Test `.../test_seed_red_flags.py`

**Interfaces:** `FollowupQuestion` is merged as `{anchor_id: row.anchor_id, text: row.followup_question}`; the constraint becomes `REQUIRE (q.anchor_id, q.text) IS UNIQUE`; the provider's traversal query (`queries.py`) needs no change because it reads through `ASKS`.

- [ ] **Step 1: Failing tests:** `test_followup_question_merge_key_includes_anchor_id`; `test_constraint_is_composite_on_anchor_id_and_text`; `test_same_text_on_two_anchors_creates_two_questions`.
- [ ] **Step 2–4:** Implement; run the module's tests. Expected: PASS. Update the module docstring that said the question is "deliberately shared".
- [ ] **Step 5: Commit** `fix(graph): scope follow-up questions per anchor`

### Task 6: Graph health report

**Files:** Create `backend/scripts/snomed_ingest/graph_health.py`; Test `.../test_graph_health.py`

**Interfaces:** Produces `component_sizes(edges: Iterable[tuple[str, str]]) -> list[int]` (union-find, descending); `@dataclass HealthReport(nodes: int, relationships: int, max_over_median_degree: float, max_is_a_in_degree: int, max_asks_in_degree: int, max_red_flag_out_degree: int, component_count: int, largest_component_share: float, anchors_loaded: int, anchors_total: int, collisions: int)`; `collect(client: Neo4jClient, anchor_ids: Sequence[str]) -> HealthReport`; `format_report(r: HealthReport) -> str` marking each advisory limit (50×, 50, 5, 20, 50,000/75,000) as `ok`/`over`.

- [ ] **Step 1: Failing tests:** `test_component_sizes_on_two_islands`; `test_collect_maps_cypher_rows_into_the_report` (fake client keyed by query text); `test_format_report_flags_values_over_limit`.
- [ ] **Step 2–4:** Implement; run. Components are computed in Python from the IS_A edge list (no GDS on Aura Free).
- [ ] **Step 5: Commit** `feat(graph): add the advisory graph health report`

### Task 7: Build orchestrator with wipe guard and tracer mode

**Files:** Create `backend/scripts/snomed_ingest/build_graph_v3.py`; Test `.../test_build_graph_v3.py`; one `@pytest.mark.integration` tracer test

**Interfaces:**
- Consumes: Tasks 1, 2, 4, 5, 6 and `seed_red_flags.seed`.
- Produces: `build(session_factory, rf2_terminology_dir: Path, *, source_release: str, lay_rule: str, anchors_limit: int | None, wipe: bool, confirm_wipe: str | None, aura_instance_id: str | None, snapshot: bool) -> BuildResult(report: HealthReport, snapshot: SnapshotResult | None)`; CLI `python -m scripts.snomed_ingest.build_graph_v3 --rf2-dir ... --source-release ... --lay-rule confirmed [--anchors-limit N] [--wipe --confirm-wipe ID] [--snapshot]`. Order: guard → (wipe) → constraints → pre-create anchors → Layer 1 (English descriptions only, assigned concepts only) → lay nodes → Layer 2 → health report → snapshot (only if the report has no `over` blocking items and anchors_loaded == anchors_total).

- [ ] **Step 1: Failing tests:** `test_wipe_without_confirm_flag_raises_and_runs_nothing`; `test_wipe_with_mismatched_confirm_raises`; `test_steps_run_in_the_documented_order` (fake session log); `test_english_only_descriptions_are_written`; `test_snapshot_is_skipped_when_anchor_coverage_incomplete`; `test_anchors_limit_builds_only_that_many_anchors`.
- [ ] **Step 2–4:** Implement; unit tests PASS.
- [ ] **Step 5:** **Tracer on the live instance** (needs `medicoord-graph` credentials via Doppler/env; never print them): `--anchors-limit 5 --wipe --confirm-wipe <id>`, then the full 154 build; record the health report in the task summary and confirm the 154/154 anchor coverage. Run the integration test with `-m integration`.
- [ ] **Step 6: Commit** `feat(graph): add the v3 graph build with a wipe guard`

### Task 8: Aura snapshot step

**Files:** Create `backend/scripts/snomed_ingest/aura_snapshot.py`; Test `.../test_aura_snapshot.py`

**Interfaces:** Produces `@dataclass(frozen=True) SnapshotResult(ok: bool, detail: str)`; `take_snapshot(instance_id: str, run=subprocess.run) -> SnapshotResult` calling `aura-cli instance snapshot create --instance-id <id>`; never raises; on a missing CLI or a non-zero exit returns `ok=False` with a message telling the operator to use the console's Take snapshot button.

- [ ] **Step 1: Failing tests:** `test_success_returns_ok`; `test_missing_cli_returns_manual_instruction`; `test_nonzero_exit_returns_failure_detail_without_raising`.
- [ ] **Step 2–4:** Implement and run. Then **live check** (first tracer): run it against the Free instance and record in the task summary whether the CLI works on Free, how many snapshots are kept, and whether a restore works (`aura-cli instance overwrite`); if not, update the spec's §9 open item and the deploy checklist.
- [ ] **Step 5: Commit** `feat(graph): add the Aura snapshot step`

### Task 9: ONNX embedder with the initialisation recipe

**Files:** Create `backend/graph/semantic/settings.py`, `embedder.py`; Test `backend/tests/graph/test_semantic_embedder.py`; Modify `backend/requirements.txt`

**Interfaces:**
- Produces: `@dataclass(frozen=True) SemanticSettings(model_dir, index_dir, threads: int = 1, deadline_ms: int = 250, top_n: int = 20, score_threshold: float, gap_margin: float, lay_rule: str, breaker_failures: int = 5, breaker_cooldown_s: float = 30.0)` with `load_settings(env: Mapping[str, str]) -> SemanticSettings` (raises on non-positive threads); `class Embedder(Protocol): name: str; dim: int; def embed(self, text: str) -> np.ndarray`; `build_session_options(threads: int, allow_spinning: bool = False) -> ort.SessionOptions` (`intra_op_num_threads=threads`, `inter_op_num_threads=1`, `ORT_SEQUENTIAL`, `session.intra_op.allow_spinning="0"` unless allowed); `mean_pool(hidden, mask)`, `cls_pool(hidden)`, `l2_normalize(v)`; `class OnnxEmbedder(model_dir: Path, settings: SemanticSettings, pooling: str, prefix: str, max_len: int = 64)` with `warm_up() -> None` and `ready: bool`.

- [ ] **Step 1: Failing tests:** `test_session_options_pin_threads_and_disable_spinning`; `test_default_threads_is_one_and_zero_is_rejected`; `test_pooling_and_normalisation_match_reference_vectors`; `test_embedder_not_ready_until_warm_up_completes` (fake session); `test_empty_text_raises_ValueError_so_callers_can_skip`; `@integration test_onnx_model_matches_torch_reference` (skipped unless `SEMANTIC_MODEL_DIR` exists; cosine ≥ 0.99 against stored reference vectors).
- [ ] **Step 2–4:** Implement: one `InferenceSession` per process; tokenizer via `tokenizers` with `TOKENIZERS_PARALLELISM=false` and `RAYON_NUM_THREADS` set from `threads`; warm-up runs five inferences on messages of 5, 12, 25 and 40 tokens. Run unit tests; add `onnxruntime`, `tokenizers`, `numpy` pins to `requirements.txt`.
- [ ] **Step 5: Commit** `feat(semantic): add the ONNX embedder with bounded threads and warm-up`

### Task 10: Offline ONNX export, quantization choice and parity check

**Files:** Create `backend/scripts/embedding_eval/export_onnx.py`; Test `backend/scripts/embedding_eval/tests/test_export_onnx.py`

**Interfaces:** Produces `choose_quantization(cpu_flags: set[str]) -> QuantConfig(weight_type: str, reduce_range: bool)` (flag `avx512_vnni` or `avx_vnni` → `QInt8`, no reduce range; otherwise `QUInt8` with `reduce_range=True`); `read_cpu_flags(cpuinfo_path: str = "/proc/cpuinfo") -> set[str]`; `export(model_key: str, out_dir: Path, quant: QuantConfig) -> None` (torch → ONNX → `quantize_dynamic`); `parity(model_key, out_dir, queries: Sequence[str]) -> ParityReport(min_cosine, hit5_delta)`; CLI writes `model.int8.onnx`, `tokenizer.json`, `export.json` (checksums, quantization, CPU flags).

- [ ] **Step 1: Failing tests:** `test_vnni_flags_select_signed_int8`; `test_no_vnni_selects_unsigned_with_reduce_range`; `test_read_cpu_flags_parses_a_fixture_cpuinfo`.
- [ ] **Step 2–4:** Implement; run unit tests. Then export `bge_small` and `biolord`; run `parity` on the 150-message author set. **Acceptance:** min cosine ≥ 0.98 and hit@5 delta ≥ −2 points versus the torch fp32 results; report both. Capture the Railway box's CPU flags (`grep -m1 flags /proc/cpuinfo` on the service shell) and re-export with them.
- [ ] **Step 5: Commit** `feat(semantic): add the offline ONNX export with CPU-matched quantization and a parity check`

### Task 11: Semantic index and manifest

**Files:** Create `backend/graph/semantic/index.py`; Test `backend/tests/graph/test_semantic_index.py`

**Interfaces:**
- Produces: `@dataclass(frozen=True) IndexRow(concept_id: str, anchor_id: str, text: str, kind: str)`; `@dataclass(frozen=True) IndexManifest(model_id: str, dim: int, pooling: str, prefix: str, lay_rule: str, rows: int, rows_sha256: str, graph_build_id: str, model_sha256: str)`; `class StaleIndexError(Exception)`; `write_index(index_dir: Path, rows: Sequence[IndexRow], matrix: np.ndarray, manifest: IndexManifest) -> None` (writes to `<dir>.tmp`, fsyncs, renames); `SemanticIndex.load(index_dir: Path, expected: IndexManifest) -> SemanticIndex` (raises `StaleIndexError` on any mismatch of the fields in `expected` or a shape mismatch); `SemanticIndex.search(vector: np.ndarray, top_n: int) -> list[Hit]` with `Hit(row: IndexRow, score: float)`, exact cosine on normalised vectors.

- [ ] **Step 1: Failing tests:** `test_search_returns_rows_in_descending_score_order`; `test_load_rejects_manifest_with_different_model_or_lay_rule_or_hash`; `test_load_rejects_a_matrix_whose_row_count_differs_from_the_manifest`; `test_write_is_atomic_a_crash_before_rename_leaves_the_old_index` (monkeypatch rename to raise); `test_missing_directory_raises_StaleIndexError`.
- [ ] **Step 2–4:** Implement and run. **Step 5: Commit** `feat(semantic): add the versioned vector index with an atomic write`

### Task 12: Index builder and non-blocking ensure_index

**Files:** Create `backend/graph/semantic/build.py`; Test `backend/tests/graph/test_semantic_build.py`

**Interfaces:**
- Consumes: Tasks 9, 11.
- Produces: `fetch_index_rows(client: Neo4jClient, lay_rule: str) -> list[IndexRow]` (English descriptions of loaded concepts plus lay descriptions allowed by the rule, each tagged with the concept's primary anchor id from the graph); `expected_manifest(rows, embedder_info, settings, graph_build_id) -> IndexManifest`; `build_index(client, embedder: Embedder, settings, out_dir: Path) -> IndexManifest`; `index_state(settings, client) -> str` in `ready|missing|stale`; CLI `python -m graph.semantic.build ensure` which **always exits 0**: state `ready` → exit at once; otherwise start `python -m graph.semantic.build run` as a detached low-priority child (`nice 19`) and exit; Neo4j or model errors are logged, never raised.

- [ ] **Step 1: Failing tests:** `test_fetch_rows_only_includes_lay_phrases_allowed_by_the_rule`; `test_index_state_is_stale_when_graph_hash_changed`; `test_ensure_exits_zero_when_neo4j_is_unreachable`; `test_ensure_spawns_background_build_when_missing` (fake spawner records the command and `nice`); `test_build_embeds_each_row_once_and_writes_atomically` (fake embedder).
- [ ] **Step 2–4:** Implement and run. **Step 5: Commit** `feat(semantic): add the index builder and non-blocking ensure step`

### Task 13: Semantic candidate source (deadline, breaker, bulkhead)

**Files:** Create `backend/graph/semantic/candidates.py`; Modify `backend/metrics.py`; Test `backend/tests/graph/test_semantic_candidates.py`

**Interfaces:**
- Produces: `@dataclass(frozen=True) Candidate(concept_id: str, anchor_id: str, score: float, text: str)`; `@dataclass(frozen=True) CandidateResult(candidates: tuple[Candidate, ...], skipped: str | None)` with `skipped` in `empty|timeout|breaker_open|not_ready|error|queue_full`; `class Breaker(failures: int, cooldown_s: float, clock: Callable[[], float])` with `allow() -> bool`, `record(ok: bool) -> None`; `SemanticCandidateSource(embedder, index, settings, clock=time.monotonic)` with `candidates(message: str) -> CandidateResult` (never raises; a worker pool of `settings.threads`, a bounded queue of `threads`; over capacity returns `queue_full` immediately); metrics `SEMANTIC_OUTCOMES = Counter("graph_semantic_outcomes_total", ..., ["outcome"])` and `SEMANTIC_EMBED_DURATION` histogram.

- [ ] **Step 1: Failing tests:** `test_whitespace_or_emoji_only_message_is_skipped_as_empty`; `test_slow_embedder_beyond_deadline_returns_timeout`; `test_second_concurrent_turn_with_full_queue_returns_queue_full_without_waiting`; `test_breaker_opens_after_n_failures_and_half_opens_after_cooldown`; `test_not_ready_embedder_is_skipped`; `test_top_n_hits_become_candidates_with_anchor_ids`.
- [ ] **Step 2–4:** Implement and run. **Step 5: Commit** `feat(semantic): add the candidate source with deadline, breaker and bounded queue`

### Task 14: Abstention rule

**Files:** Create `backend/graph/semantic/abstention.py`; Test `backend/tests/graph/test_semantic_abstention.py`

**Interfaces:** Produces `anchor_scores(candidates: Sequence[Candidate]) -> dict[str, float]` (max per anchor); `@dataclass(frozen=True) Decision(accepted: bool, reason: str)`; `decide(scores: Mapping[str, float], threshold: float, margin: float) -> Decision` (accept iff top score ≥ threshold and, when a second anchor exists, top − second ≥ margin; reasons `low_score`, `small_gap`, `ok`, `no_candidates`).

- [ ] **Step 1: Failing tests:** `test_accepts_when_both_conditions_hold`; `test_rejects_low_top_score`; `test_rejects_when_gap_to_second_is_small`; `test_single_anchor_needs_only_the_threshold`; `test_empty_scores_are_rejected`; `test_anchor_scores_takes_the_max_per_anchor`.
- [ ] **Step 2–4:** Implement and run. **Step 5: Commit** `feat(semantic): add the abstention rule`

### Task 15: Provider seam, `Neo4jSemanticProvider`, factory

**Files:** Modify `backend/graph/snomed_neo4j/provider.py`, `backend/graph/factory.py`; Create `backend/graph/snomed_neo4j/semantic_provider.py`; Test `backend/tests/graph/test_semantic_provider.py`; existing `test_snomed_provider.py`/`test_factory.py` must pass

**Interfaces:**
- Consumes: Tasks 13, 14.
- Produces: in `Neo4jSnomedProvider`, `_gather_candidates(self, user_message: str, all_text: str) -> dict[str, float]` (concept id → specificity; v2 returns the lexical rows' `matched_length`), used by `_resolve_surviving_mappings(all_text, user_message=None)`; `Neo4jSemanticProvider(source: SemanticCandidateSource | None = None, settings: SemanticSettings | None = None)` overriding `_gather_candidates`: lexical hits with `matched_length >= LEXICAL_PRECEDENCE_MIN_LEN (12)` get `1000 + length`; shorter lexical hits get `length / 1000`; semantic candidates get their cosine score only if `decide(...)` accepts; `semantic_status() -> dict` (`state` in `ready|warming|building|stale|disabled`, `model`, `rows`); factory value `neo4j_semantic`.

- [ ] **Step 1: Failing tests:** `test_v2_provider_behaviour_is_unchanged` (existing suite); `test_lexical_exact_hit_outranks_semantic_candidates`; `test_short_lexical_hit_does_not_outrank_a_semantic_hit`; `test_semantic_timeout_falls_back_to_lexical_result`; `test_abstained_semantic_part_is_dropped_but_lexical_kept`; `test_stale_index_serves_lexical_only_and_reports_stale`; `test_empty_message_returns_matched_false_without_error`; `test_factory_builds_semantic_provider_for_the_new_value_and_leaves_neo4j_alone`.
- [ ] **Step 2–4:** Implement; run `doppler run -- pytest backend/tests/graph -v`. Expected: all PASS.
- [ ] **Step 5: Commit** `feat(graph): add the neo4j_semantic provider behind its own flag`

### Task 16: Wiring, health and start command

**Files:** Modify `backend/main.py` (`/health`), `backend/graph/semantic/build.py` docs; Test `backend/tests/test_health.py`

**Interfaces:** `/health` keep-alive ping runs for `GRAPH_RAG_PROVIDER` in `{"neo4j", "neo4j_semantic"}` and adds `result["semantic"] = provider.semantic_status()` for the latter; the provider starts its warm-up in a background thread at construction (the app starts at once; state `warming` until done) and re-checks the index manifest at most every 60 s (`SEMANTIC_RELOAD_S`), loading a newer valid index atomically (`maybe_reload() -> bool` on `Neo4jSemanticProvider`).

- [ ] **Step 1: Failing tests:** `test_health_pings_neo4j_for_the_semantic_provider_value`; `test_health_reports_semantic_state_and_never_fails_when_status_raises`; `test_provider_loads_a_newer_valid_index_and_ignores_a_stale_one`.
- [ ] **Step 2–4:** Implement and run. 
- [ ] **Step 5 (operations, user-run):** in the Railway service settings, set the start command to `python -m graph.semantic.build ensure; uvicorn main:app --host 0.0.0.0 --port $PORT` (`;` so the API starts even if ensure fails), confirm the volume mount path and set `SEMANTIC_INDEX_DIR`/`SEMANTIC_MODEL_DIR` under it, and copy the exported model directory to the volume (Railway CLI or SFTP/SCP; `RAILWAY_RUN_UID=0` if the image is non-root). Record the confirmed settings in the task summary.
- [ ] **Step 6: Commit** `feat(graph): report semantic status in health and start the warm-up in the background`

### Task 17: Negative set and threshold calibration

**Files:** Create `backend/scripts/embedding_eval/data/negative_queries.json`, `calibrate.py`; Test `.../tests/test_calibrate.py`

**Interfaces:** Produces `@dataclass Thresholds(threshold: float, margin: float, in_scope_retained: float, false_match: float)`; `calibrate_thresholds(in_scope: Sequence[tuple[float, float]], out_of_scope: Sequence[tuple[float, float]], target_false_match: float = 0.05) -> Thresholds` where each pair is (top score, gap to second); grid search maximising in-scope retention subject to the false-match target; `split_negative_set(items, seed) -> tuple[list, list]` (validation / test).

- [ ] **Step 1: Failing tests:** `test_calibration_meets_false_match_target_on_separable_data`; `test_calibration_returns_most_permissive_pair_meeting_the_target`; `test_unsatisfiable_target_returns_the_strictest_pair_and_reports_actual_false_match`; `test_split_is_deterministic_for_a_seed`.
- [ ] **Step 2–4:** Implement. Author `negative_queries.json` with 120 messages in the six categories of spec §8.5 (about 20 each: off-topic chat, health-admin, symptoms outside the 154 anchors, near-misses, empty/very short, injection-style), each with a `category`; the user reviews it. No paid call.
- [ ] **Step 5: Commit** `feat(eval): add the negative query set and threshold calibration`

### Task 18: Evaluate the shipped index (retrieval screen) and the third-generator set

**Files:** Create `backend/scripts/embedding_eval/eval_index.py`; Modify `gen_queries.py` (provider via `EVAL_GEN_BASE_URL`, `EVAL_GEN_API_KEY_ENV`); Test `.../tests/test_eval_index.py`

**Interfaces:** Produces `evaluate(index: SemanticIndex, embedder: Embedder, queries: Sequence[dict], negatives: Sequence[dict], thresholds: Thresholds) -> ScreenReport(hit1, hit5, hit5_ci95, false_match, in_scope_retained, p50_ms, p95_ms)` and `passes_screen(r: ScreenReport) -> bool` (hit5 lower bound ≥ 75 and false_match ≤ 0.05); CLI prints PASS/FAIL per query set. Uses the production `OnnxEmbedder` and `SemanticIndex`, so what ships is what is measured.

- [ ] **Step 1: Failing tests:** `test_hit_rates_on_a_toy_index`; `test_passes_screen_requires_both_conditions`; `test_gen_queries_reads_base_url_and_key_env_for_a_non_openai_provider`.
- [ ] **Step 2–4:** Implement. Generate the third-generator set with Groq (free, no spend; model name from env): about 300 messages through `gen_queries first`-style flow into `data/generated_third_labeled.json`. Run the screen for BioLORD and bge-small on the author, generated and third-generator sets and report the table.
- [ ] **Step 5:** **Gate (spec step 4):** if neither model passes, stop and record why before any paid pilot.
- [ ] **Step 6: Commit** `feat(eval): evaluate the shipped index against the screen`

### Task 19: CPU and latency benchmark on the Railway box

**Files:** Create `backend/scripts/embedding_eval/bench_embedder.py`; Test `.../tests/test_bench_stats.py`

**Interfaces:** Produces `latency_stats(samples_ms: Sequence[float]) -> dict` (p50, p95, p99, max); `capacity_estimate(added_ms: float, base_cpu_ms: float = 16.0, base_capacity: float = 35.0) -> float` = `base_capacity * base_cpu_ms / (base_cpu_ms + added_ms)`; CLI runs: first-call latency, 200 steady calls, RSS memory, thread count, with `EMBED_THREADS` 1 and 2.

- [ ] **Step 1: Failing tests:** `test_latency_stats_percentiles`; `test_capacity_estimate_matches_the_sprint_22_formula` (X=50 → about 8.5).
- [ ] **Step 2–4:** Implement; run unit tests; then run the script **on the python-api service** for both exported models and record first-call vs steady-state, p95, RSS and the estimated capacity against the budgets; revisit the budgets and `EMBED_DEADLINE_MS` from the measured p95.
- [ ] **Step 5: Commit** `feat(eval): add the embedder latency and capacity benchmark`

### Task 20: End-to-end leg provenance

**Files:** Modify `backend/scripts/symptom_eval/run_manifest.py`, `cli.py`; Test `backend/scripts/symptom_eval/tests/test_run_manifest.py`, `test_cli.py`

**Interfaces:** `RunManifest` gains `graph_index_manifest_sha256: str` and `semantic_model_id: str` (empty strings when no semantic leg), included in the resume check; `build_manifest(...)` reads `SEMANTIC_INDEX_DIR`'s manifest when `providers` contains `neo4j_semantic`.

- [ ] **Step 1: Failing tests:** `test_manifest_mismatch_when_the_index_changes_between_resumes`; `test_manifest_has_empty_semantic_fields_without_a_semantic_leg`; `test_build_manifest_reads_the_index_manifest_hash`.
- [ ] **Step 2–4:** Implement; run `doppler run -- pytest backend/scripts/symptom_eval -q`. Expected: PASS. Then run the dry run with `--providers off,static,neo4j_semantic` to confirm the leg is accepted.
- [ ] **Step 5: Commit** `feat(eval): record the semantic index in the run manifest`

### Task 21 (follow-on, after the step 5 pilot): input-text experiment

Needs the pilot's persisted transcripts. Compare current message only, concatenation of recent user messages, and per-message embeddings fused by max per anchor, on multi-turn conversations, with the same screen. Files: `eval_index.py --input-mode {current,concat,fused}`. Tests: `test_input_modes_build_the_expected_query_texts`. Commit `feat(eval): compare embedding input modes on multi-turn transcripts`. Not part of the step 4 gate.

---

## Self-review

- **Spec coverage:** build rules and depth/primary anchor (1), lay layer (2, 3, 4), question scoping (5), health checks (6), build/wipe/snapshot (7, 8), runtime init (9), export/quantization (10), index/manifest (11), deploy-time build (12, 16), deadline/breaker/bulkhead (13), abstention (14, 17), provider/fallback/lexical-first (15), health/flag (15, 16), screen and independent test set (18), latency/capacity (19), provenance (20), input text (21).
- **Type consistency:** `Candidate`, `CandidateResult`, `IndexRow`, `IndexManifest`, `SemanticSettings`, `Decision`, `Thresholds`, `HealthReport` and `SnapshotResult` are defined once and referenced by name later.
- **Skills applied:** clean-architecture (ports/adapters, wiring in factory/main), pragmatic-programmer (tracer builds in Tasks 7 and 18, reversible flag), clean-code (small named stages), ddia-systems (derived vector data with manifest and staleness), release-it (deadline, breaker, bulkhead, deep health), test-driven-development (tests first in every task).
