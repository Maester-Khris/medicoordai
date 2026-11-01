# Guest Demo Sprint 2, Phase 2 (code) Implementation Plan

**Goal:** Give the demo API the metrics, settings and provider fallback the Phase 2 measurements
need, the k6 scripts to run them, and the fix for chat turns blocking the single worker.

**Architecture:** One `metrics` module owns every new metric and a timing helper; routing, the
graph lookup and the LLM clients use it. LLM timing and provider fallback are wrappers around the
existing provider interface, so the agent and the provider clients barely change. Settings are
read from the environment through one validated reader. The broken Grafana push is deleted in
favour of Grafana scraping `/metrics`.

**Tech stack:** Python / FastAPI / prometheus_client / psycopg_pool / httpx / the Groq, OpenAI and
Anthropic SDKs; k6 through its official container image.

**Spec:** `docs/superpowers/specs/2026-10-10-guest-demo-sprint2-phase2-design.md`. This plan covers
Part A (code). Part B, the measurement runbook, is section 10 of the spec.

## How to read this plan

Twelve tasks, one commit each, in this order. Every code task was done test-first: the tests were
added, run to see them fail for the stated reason, then the code was added and the tests run
again. The whole sequence was replayed in order on a clean checkout before it was landed, so the
failing and passing results quoted under each task are real output, not predictions.

For each task the plan gives the files, what the task provides to later tasks, the test change,
the failing result, the code change and the passing result.

## Constraints the work follows

- One Python environment, `/home/niki/Documents/workenv/pydev/`; tests run as
  `doppler run -- pytest ...` inside `backend/`.
- No new dependency, in Python or on the host. k6 runs from its container image.
- One conventional one-line commit per task.
- Task 12 is the last commit on purpose: the measurement runbook deploys the commit before it
  first, to measure the chat path before and after the fix.

## Review Focus

Conditions the spec implies that are easy to get wrong. Each is pinned by a test in the task named.

1. A provider call fails with a rate limit and the next provider answers: both attempts must be
   counted, each under its own provider label, and the answer returned (Task 6
   `test_a_failed_call_is_counted_under_its_outcome_and_re_raised`, Task 8
   `test_a_provider_side_failure_moves_to_the_next_provider`).
2. A request the provider rejects as malformed (400, 422) must not be retried on another
   provider: it would fail there too and hide a bug (Task 8
   `test_a_request_side_failure_is_raised_without_trying_another_provider`).
3. With `LLM_PROVIDER_CHAIN` unset, behaviour must be exactly today's, including the SDK's own
   retries (Task 9
   `test_without_a_chain_the_default_is_one_instrumented_groq_client_with_sdk_retries`).
4. A setting with a bad value (`DEMO_DB_POOL_MAX=many`, `RATE_LIMIT_ROUTES_IP=0`) must not stop
   the API from starting (Task 1 `test_env_int_falls_back_on_a_malformed_or_out_of_range_value`,
   Task 2 `test_an_invalid_pool_size_falls_back_to_the_default`).
5. `/metrics` with no token configured must be closed, not open (Task 5
   `test_metrics_is_closed_when_no_token_is_configured`).
6. A chat turn must not run on the event loop (Task 12
   `test_agent_and_message_writes_run_in_the_thread_pool`).

## File Structure

| File | Status | Responsibility |
|---|---|---|
| `backend/metrics.py` | create | Metric objects, `timed`, pool gauge binding |
| `backend/config.py` | modify | `env_int`, `llm_timeout_seconds`, `llm_provider_chain` |
| `backend/demo_db.py` | modify | Pool size and wait from settings; `pool_stats` |
| `backend/services/rate_limit.py`, `backend/routers/routes.py` | modify | Limits from settings |
| `backend/services/routing.py`, `backend/graph/base.py` | modify | Timing; status code in the routing failure log |
| `backend/observability.py` | modify | Push thread removed; `/metrics` closed without a token |
| `backend/llm/instrumented.py` | create | Error classification, `InstrumentedLLMClient` |
| `backend/llm/openai_client.py` | create | OpenAI provider |
| `backend/llm/fallback.py` | create | `FallbackLLMClient` |
| `backend/services/llm_agent.py`, `backend/llm/groq_client.py`, `backend/llm/anthropic_client.py` | modify | Factory, timeouts, retries |
| `backend/scripts/load/*` | create | k6 scripts |
| `docs/API.md`, `CHANGELOG.md` | modify | Documentation |
| `backend/routers/chat.py` | modify | Blocking calls moved to the thread pool |

---

# Part 1 — Metrics, settings, Grafana

### Task 1: Metrics module and integer settings

**Commit:** `feat: add application metrics module and integer settings from the environment`

**Files:**
- Modify: `backend/config.py`
- Create: `backend/metrics.py`
- Modify: `backend/tests/test_config.py`
- Create: `backend/tests/test_metrics.py`

**Interfaces:** Produces: `metrics.timed(histogram, **labels)` (context manager yielding an object with an `outcome` attribute), `metrics.bind_pool_stats(read_stats)`, the metric objects `LLM_CALL_DURATION`, `LLM_CALLS`, `LLM_TOKENS`, `ROUTING_CALL_DURATION`, `GRAPH_LOOKUP_DURATION`; `config.env_int(name, default, minimum=1, maximum=None)`, `config.llm_timeout_seconds()`, `config.llm_provider_chain()`.

**Step 1 — tests first.**

```diff
diff --git a/backend/tests/test_config.py b/backend/tests/test_config.py
index fbde35c..9099aee 100644
--- a/backend/tests/test_config.py
+++ b/backend/tests/test_config.py
@@ -29,3 +29,37 @@ def test_starter_prompts_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
 def test_starter_prompts_fall_back_on_bad_env(monkeypatch: pytest.MonkeyPatch, bad: str) -> None:
     monkeypatch.setenv("DEMO_STARTER_PROMPTS", bad)
     assert config.starter_prompts() == config.DEFAULT_STARTER_PROMPTS
+
+
+def test_env_int_returns_the_default_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
+    monkeypatch.delenv("SOME_SETTING", raising=False)
+    assert config.env_int("SOME_SETTING", 7) == 7
+
+
+def test_env_int_reads_a_valid_value(monkeypatch: pytest.MonkeyPatch) -> None:
+    monkeypatch.setenv("SOME_SETTING", " 42 ")
+    assert config.env_int("SOME_SETTING", 7) == 42
+
+
+@pytest.mark.parametrize("raw", ["abc", "1.5", "0", "-1", "999"])
+def test_env_int_falls_back_on_a_malformed_or_out_of_range_value(
+    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, raw: str
+) -> None:
+    monkeypatch.setenv("SOME_SETTING", raw)
+    with caplog.at_level("WARNING"):
+        assert config.env_int("SOME_SETTING", 7, minimum=1, maximum=100) == 7
+    assert [rec.getMessage() for rec in caplog.records] == ["env_setting_invalid"]
+
+
+def test_llm_timeout_defaults_to_thirty_seconds(monkeypatch: pytest.MonkeyPatch) -> None:
+    monkeypatch.delenv("LLM_TIMEOUT_SECONDS", raising=False)
+    assert config.llm_timeout_seconds() == 30
+    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "12")
+    assert config.llm_timeout_seconds() == 12
+
+
+def test_provider_chain_is_empty_when_unset_and_ordered_when_set(monkeypatch: pytest.MonkeyPatch) -> None:
+    monkeypatch.delenv("LLM_PROVIDER_CHAIN", raising=False)
+    assert config.llm_provider_chain() == []
+    monkeypatch.setenv("LLM_PROVIDER_CHAIN", " Groq, openai ,,anthropic ")
+    assert config.llm_provider_chain() == ["groq", "openai", "anthropic"]
diff --git a/backend/tests/test_metrics.py b/backend/tests/test_metrics.py
new file mode 100644
index 0000000..05993d3
--- /dev/null
+++ b/backend/tests/test_metrics.py
@@ -0,0 +1,88 @@
+import os
+import sys
+
+sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
+
+import pytest
+from prometheus_client import CollectorRegistry, Histogram
+
+import metrics
+from observability import _registry
+
+
+@pytest.fixture()
+def histogram() -> Histogram:
+    return Histogram("probe_seconds", "test", ["kind", "outcome"], registry=CollectorRegistry())
+
+
+def _observations(histogram: Histogram, **labels: str) -> float:
+    for family in histogram.collect():
+        for sample in family.samples:
+            if sample.name.endswith("_count") and sample.labels == labels:
+                return sample.value
+    return 0.0
+
+
+def test_timed_records_one_ok_observation(histogram: Histogram) -> None:
+    with metrics.timed(histogram, kind="a"):
+        pass
+    assert _observations(histogram, kind="a", outcome="ok") == 1.0
+
+
+def test_timed_uses_the_outcome_the_block_sets(histogram: Histogram) -> None:
+    with metrics.timed(histogram, kind="a") as timing:
+        timing.outcome = "no_route"
+    assert _observations(histogram, kind="a", outcome="no_route") == 1.0
+    assert _observations(histogram, kind="a", outcome="ok") == 0.0
+
+
+def test_timed_records_an_escaping_exception_as_error_and_re_raises_it(histogram: Histogram) -> None:
+    boom = ValueError("boom")
+    with pytest.raises(ValueError) as caught:
+        with metrics.timed(histogram, kind="a"):
+            raise boom
+    assert caught.value is boom
+    assert _observations(histogram, kind="a", outcome="error") == 1.0
+
+
+def test_timed_keeps_a_specific_outcome_when_the_block_raises(histogram: Histogram) -> None:
+    with pytest.raises(RuntimeError):
+        with metrics.timed(histogram, kind="a") as timing:
+            timing.outcome = "rate_limited"
+            raise RuntimeError("429")
+    assert _observations(histogram, kind="a", outcome="rate_limited") == 1.0
+    assert _observations(histogram, kind="a", outcome="error") == 0.0
+
+
+def test_timed_measures_elapsed_seconds(histogram: Histogram, monkeypatch: pytest.MonkeyPatch) -> None:
+    ticks = iter([100.0, 102.5])
+    monkeypatch.setattr(metrics.time, "perf_counter", lambda: next(ticks))
+    with metrics.timed(histogram, kind="a"):
+        pass
+    total = [s.value for f in histogram.collect() for s in f.samples
+             if s.name.endswith("_sum") and s.labels == {"kind": "a", "outcome": "ok"}]
+    assert total == [2.5]
+
+
+def test_application_metrics_are_on_the_registry_served_by_metrics_endpoint() -> None:
+    names = {family.name for family in _registry.collect()}
+    assert {
+        "llm_call_duration_seconds", "llm_calls", "llm_tokens",
+        "routing_call_duration_seconds", "graph_lookup_duration_seconds",
+        "demo_db_pool_size", "demo_db_pool_in_use", "demo_db_pool_waiting",
+    } <= names
+
+
+def test_pool_gauges_read_the_bound_function_at_scrape_time() -> None:
+    state = {"size": 4, "in_use": 3, "waiting": 2}
+    metrics.bind_pool_stats(lambda: state)
+    try:
+        assert _registry.get_sample_value("demo_db_pool_size") == 4
+        assert _registry.get_sample_value("demo_db_pool_in_use") == 3
+        state["waiting"] = 7
+        assert _registry.get_sample_value("demo_db_pool_waiting") == 7
+    finally:
+        # Put back the real reader when demo_db provides one, so later tests see live gauges.
+        import demo_db
+        zeros = {"size": 0, "in_use": 0, "waiting": 0}
+        metrics.bind_pool_stats(getattr(demo_db, "pool_stats", lambda: zeros))
```

**Step 2 — the tests fail without the code.** `pytest tests/test_config.py tests/test_metrics.py -q` ends with `1 error in 0.20s`:

```text
E   ModuleNotFoundError: No module named 'metrics'
ERROR tests/test_metrics.py
```

**Step 3 — the code.**

```diff
diff --git a/backend/config.py b/backend/config.py
index 8a76cbb..534afb4 100644
--- a/backend/config.py
+++ b/backend/config.py
@@ -1,7 +1,10 @@
 """Demo-mode switch and constants. Read through functions so tests can flip the environment."""
 import json
+import logging
 import os
 
+logger = logging.getLogger(__name__)
+
 DOWNTOWN_TORONTO: dict[str, float] = {"lat": 43.6532, "lng": -79.3832}
 ALL_MODES: list[str] = ["car", "bike", "bus", "walk"]
 DEMO_MODES: list[str] = ["car", "bike", "bus", "walk"]  # every mode is a real route since sprint 21
@@ -38,3 +41,30 @@ def starter_prompts() -> list[str]:
 
 def internal_token() -> str:
     return os.environ.get("DEMO_INTERNAL_TOKEN", "").strip()
+
+
+def env_int(name: str, default: int, minimum: int = 1, maximum: int | None = None) -> int:
+    """An integer setting from the environment. A missing, malformed or out-of-range value
+    falls back to `default` with one warning: a bad setting must never stop the API from starting."""
+    raw = os.environ.get(name, "").strip()
+    if not raw:
+        return default
+    try:
+        value = int(raw)
+    except ValueError:
+        logger.warning("env_setting_invalid", extra={"setting": name, "reason": "not an integer"})
+        return default
+    if value < minimum or (maximum is not None and value > maximum):
+        logger.warning("env_setting_invalid", extra={"setting": name, "reason": "out of range"})
+        return default
+    return value
+
+
+def llm_timeout_seconds() -> int:
+    return env_int("LLM_TIMEOUT_SECONDS", 30, minimum=1, maximum=300)
+
+
+def llm_provider_chain() -> list[str]:
+    """Ordered provider names from LLM_PROVIDER_CHAIN ("groq,openai,anthropic"); empty when unset."""
+    raw = os.environ.get("LLM_PROVIDER_CHAIN", "")
+    return [name.strip().lower() for name in raw.split(",") if name.strip()]
diff --git a/backend/metrics.py b/backend/metrics.py
new file mode 100644
index 0000000..78390b7
--- /dev/null
+++ b/backend/metrics.py
@@ -0,0 +1,78 @@
+"""Application metrics beyond the per-route ones the instrumentator records.
+
+Everything registers on the registry /metrics already serves. This module knows nothing about
+the LLM, routing, graph or database code: they import it, it imports none of them.
+
+Label values are small fixed sets (provider, travel mode, outcome). Never put a guest, session,
+message or facility value in a label: every distinct value becomes a time series.
+"""
+import time
+from collections.abc import Callable, Iterator
+from contextlib import contextmanager
+
+from prometheus_client import Counter, Gauge, Histogram
+
+from observability import _registry
+
+# Buckets sit around the values already observed (LLM 1.5 to 10 s, routing 0.5 to 3 s), so
+# percentiles interpolate inside populated buckets.
+LLM_BUCKETS = (0.25, 0.5, 1, 2, 3, 5, 8, 13, 21, 34)
+ROUTING_BUCKETS = (0.1, 0.25, 0.5, 1, 2, 3, 5, 8)
+GRAPH_BUCKETS = (0.005, 0.025, 0.1, 0.25, 0.5, 1, 2.5)
+
+LLM_CALL_DURATION = Histogram(
+    "llm_call_duration_seconds", "One LLM provider call, end to end",
+    ["provider", "outcome"], buckets=LLM_BUCKETS, registry=_registry,
+)
+LLM_CALLS = Counter(
+    "llm_calls_total", "LLM provider calls by outcome (ok, rate_limited, timeout, error)",
+    ["provider", "outcome"], registry=_registry,
+)
+LLM_TOKENS = Counter(
+    "llm_tokens_total", "Tokens reported by the provider (kind: prompt, completion)",
+    ["provider", "kind"], registry=_registry,
+)
+ROUTING_CALL_DURATION = Histogram(
+    "routing_call_duration_seconds", "One Geoapify Routing call for one candidate facility",
+    ["mode", "outcome"], buckets=ROUTING_BUCKETS, registry=_registry,
+)
+GRAPH_LOOKUP_DURATION = Histogram(
+    "graph_lookup_duration_seconds", "One symptom graph context lookup",
+    ["provider", "outcome"], buckets=GRAPH_BUCKETS, registry=_registry,
+)
+POOL_SIZE = Gauge("demo_db_pool_size", "Connections open in the demo database pool", registry=_registry)
+POOL_IN_USE = Gauge("demo_db_pool_in_use", "Connections currently checked out", registry=_registry)
+POOL_WAITING = Gauge("demo_db_pool_waiting", "Callers waiting for a free connection", registry=_registry)
+
+
+class Timing:
+    """What a `timed` block reports. Set `outcome` inside the block; it defaults to "ok"."""
+
+    def __init__(self) -> None:
+        self.outcome = "ok"
+
+
+@contextmanager
+def timed(histogram: Histogram, **labels: str) -> Iterator[Timing]:
+    """Observes how long the block took, labelled with `labels` plus the block's outcome.
+
+    An exception leaving the block is recorded as outcome "error" unless the block already set
+    something more specific, and is always re-raised unchanged.
+    """
+    timing = Timing()
+    started = time.perf_counter()
+    try:
+        yield timing
+    except BaseException:
+        if timing.outcome == "ok":
+            timing.outcome = "error"
+        raise
+    finally:
+        histogram.labels(**labels, outcome=timing.outcome).observe(time.perf_counter() - started)
+
+
+def bind_pool_stats(read_stats: Callable[[], dict[str, int]]) -> None:
+    """Makes the three pool gauges read `read_stats()` at scrape time. Called once by demo_db."""
+    POOL_SIZE.set_function(lambda: read_stats()["size"])
+    POOL_IN_USE.set_function(lambda: read_stats()["in_use"])
+    POOL_WAITING.set_function(lambda: read_stats()["waiting"])
```

**Step 4 — the tests pass.** `pytest tests/test_config.py tests/test_metrics.py -q` ends with `29 passed in 0.22s`.

### Task 2: Database pool: size from the environment, usage exported

**Commit:** `feat: size the demo database pool from the environment and export its usage`

**Files:**
- Modify: `backend/demo_db.py`
- Create: `backend/tests/test_demo_db_pool.py`

**Interfaces:** Consumes: `config.env_int`, `metrics.bind_pool_stats` (Task 1). Produces: `demo_db.pool_stats() -> dict` with keys `size`, `in_use`, `waiting`; settings `DEMO_DB_POOL_MAX`, `DEMO_DB_POOL_TIMEOUT_SECONDS`.

**Step 1 — tests first.**

```diff
diff --git a/backend/tests/test_demo_db_pool.py b/backend/tests/test_demo_db_pool.py
new file mode 100644
index 0000000..8c9782e
--- /dev/null
+++ b/backend/tests/test_demo_db_pool.py
@@ -0,0 +1,62 @@
+import os
+import sys
+
+sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
+
+from unittest.mock import MagicMock, patch
+
+import pytest
+
+import demo_db
+
+
+@pytest.fixture(autouse=True)
+def _no_pool(monkeypatch: pytest.MonkeyPatch):
+    monkeypatch.setattr(demo_db, "_pool", None)
+    monkeypatch.setenv("POSTGRES_DB_URL_APP", "postgresql://u:p@localhost:1/db")
+    yield
+    monkeypatch.setattr(demo_db, "_pool", None)
+
+
+def _open_with_fake_pool() -> dict:
+    with patch.object(demo_db, "ConnectionPool") as pool_class:
+        demo_db.open_pool()
+    return pool_class.call_args.kwargs
+
+
+def test_pool_uses_the_defaults_when_nothing_is_set(monkeypatch: pytest.MonkeyPatch) -> None:
+    monkeypatch.delenv("DEMO_DB_POOL_MAX", raising=False)
+    monkeypatch.delenv("DEMO_DB_POOL_TIMEOUT_SECONDS", raising=False)
+    kwargs = _open_with_fake_pool()
+    assert (kwargs["min_size"], kwargs["max_size"], kwargs["timeout"]) == (1, 5, 5)
+
+
+def test_pool_size_and_timeout_come_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
+    monkeypatch.setenv("DEMO_DB_POOL_MAX", "12")
+    monkeypatch.setenv("DEMO_DB_POOL_TIMEOUT_SECONDS", "2")
+    kwargs = _open_with_fake_pool()
+    assert (kwargs["max_size"], kwargs["timeout"]) == (12, 2)
+
+
+@pytest.mark.parametrize("bad", ["0", "-3", "51", "many", ""])
+def test_an_invalid_pool_size_falls_back_to_the_default(monkeypatch: pytest.MonkeyPatch, bad: str) -> None:
+    monkeypatch.setenv("DEMO_DB_POOL_MAX", bad)
+    assert _open_with_fake_pool()["max_size"] == 5
+
+
+def test_pool_stats_are_zero_before_the_pool_exists() -> None:
+    assert demo_db.pool_stats() == {"size": 0, "in_use": 0, "waiting": 0}
+
+
+def test_pool_stats_come_from_the_pool(monkeypatch: pytest.MonkeyPatch) -> None:
+    pool = MagicMock()
+    pool.get_stats.return_value = {"pool_size": 5, "pool_available": 2, "requests_waiting": 3}
+    monkeypatch.setattr(demo_db, "_pool", pool)
+    assert demo_db.pool_stats() == {"size": 5, "in_use": 3, "waiting": 3}
+
+
+def test_pool_stats_never_raise(monkeypatch: pytest.MonkeyPatch) -> None:
+    pool = MagicMock()
+    pool.get_stats.side_effect = RuntimeError("pool closed")
+    monkeypatch.setattr(demo_db, "_pool", pool)
+    assert demo_db.pool_stats() == {"size": 0, "in_use": 0, "waiting": 0}
```

**Step 2 — the tests fail without the code.** `pytest tests/test_demo_db_pool.py -q` ends with `4 failed, 6 passed in 0.19s`:

```text
E       AttributeError: module 'demo_db' has no attribute 'pool_stats'
E       AttributeError: module 'demo_db' has no attribute 'pool_stats'
E       AttributeError: module 'demo_db' has no attribute 'pool_stats'
FAILED tests/test_demo_db_pool.py::test_pool_size_and_timeout_come_from_the_environment
```

**Step 3 — the code.**

```diff
diff --git a/backend/demo_db.py b/backend/demo_db.py
index 9ea24b4..05eaba6 100644
--- a/backend/demo_db.py
+++ b/backend/demo_db.py
@@ -4,6 +4,7 @@ Only services/guest_store.py and the demo branches of services/facilities.py and
 services/wait_times.py import this. Every call takes a connection for one statement; the
 `with pool.connection()` block commits on success and rolls back on error.
 """
+import logging
 import os
 from collections.abc import Mapping, Sequence
 from typing import Any
@@ -11,6 +12,11 @@ from typing import Any
 from psycopg.rows import dict_row
 from psycopg_pool import ConnectionPool
 
+import metrics
+from config import env_int
+
+logger = logging.getLogger(__name__)
+
 Params = Sequence[Any] | Mapping[str, Any]
 
 _pool: ConnectionPool | None = None
@@ -27,8 +33,9 @@ def open_pool() -> ConnectionPool:
         _pool = ConnectionPool(
             _conninfo(),
             min_size=1,
-            max_size=5,
-            timeout=5,  # seconds to wait for a free connection
+            max_size=env_int("DEMO_DB_POOL_MAX", 5, minimum=1, maximum=50),
+            # seconds to wait for a free connection
+            timeout=env_int("DEMO_DB_POOL_TIMEOUT_SECONDS", 5, minimum=1, maximum=60),
             kwargs={"row_factory": dict_row, "options": "-c statement_timeout=5000"},
             open=True,
         )
@@ -42,6 +49,27 @@ def close_pool() -> None:
         _pool = None
 
 
+def pool_stats() -> dict[str, int]:
+    """Connections open, in use and callers waiting, for the /metrics gauges. Zeros before the
+    pool exists; never raises (a scrape must not fail because the pool is unhealthy)."""
+    if _pool is None:
+        return {"size": 0, "in_use": 0, "waiting": 0}
+    try:
+        stats = _pool.get_stats()
+    except (RuntimeError, AttributeError, TypeError, ValueError) as exc:
+        logger.warning("demo_db_pool_stats_failed", extra={"error_type": type(exc).__name__})
+        return {"size": 0, "in_use": 0, "waiting": 0}
+    size = int(stats.get("pool_size", 0))
+    return {
+        "size": size,
+        "in_use": size - int(stats.get("pool_available", 0)),
+        "waiting": int(stats.get("requests_waiting", 0)),
+    }
+
+
+metrics.bind_pool_stats(pool_stats)
+
+
 def fetch_all(sql: str, params: Params = ()) -> list[dict[str, Any]]:
     with open_pool().connection() as conn:
         return conn.execute(sql, params).fetchall()
```

**Step 4 — the tests pass.** `pytest tests/test_demo_db_pool.py -q` ends with `10 passed in 0.21s`.

### Task 3: Rate limits from the environment

**Commit:** `feat: read rate limits from the environment with unchanged defaults`

**Files:**
- Modify: `backend/routers/routes.py`
- Modify: `backend/services/rate_limit.py`
- Modify: `backend/tests/test_rate_limit.py`
- Modify: `backend/tests/test_routes_router.py`

**Interfaces:** Consumes: `config.env_int` (Task 1). Produces: `rate_limit.limits_for(bucket) -> (guest_limit, ip_limit)`; `check_rate_limit(..., bucket=..., guest_limit=None, ip_limit=None)` resolves missing limits from `limits_for`. `routers/routes.py` now passes only `bucket="routes"`.

**Step 1 — tests first.**

```diff
diff --git a/backend/tests/test_rate_limit.py b/backend/tests/test_rate_limit.py
index 9fd98ac..b5335ba 100644
--- a/backend/tests/test_rate_limit.py
+++ b/backend/tests/test_rate_limit.py
@@ -128,3 +128,35 @@ def test_keys_are_namespaced_by_bucket(fake_redis) -> None:
     rate_limit.check_rate_limit("g1", "3.3.3.3", now=0.0, bucket="routes")
     assert any(key.startswith("rl:chat:guest:g1:") for key in fake_redis.counts)
     assert any(key.startswith("rl:routes:guest:g1:") for key in fake_redis.counts)
+
+
+def test_limits_default_to_the_constants(monkeypatch: pytest.MonkeyPatch) -> None:
+    for name in ("RATE_LIMIT_CHAT_GUEST", "RATE_LIMIT_CHAT_IP", "RATE_LIMIT_ROUTES_GUEST", "RATE_LIMIT_ROUTES_IP"):
+        monkeypatch.delenv(name, raising=False)
+    assert rate_limit.limits_for("chat") == (10, 30)
+    assert rate_limit.limits_for("routes") == (60, 180)
+
+
+def test_limits_can_be_raised_from_the_environment(fake_redis, monkeypatch: pytest.MonkeyPatch) -> None:
+    monkeypatch.setenv("RATE_LIMIT_CHAT_GUEST", "3")
+    monkeypatch.setenv("RATE_LIMIT_CHAT_IP", "1000")
+    assert rate_limit.limits_for("chat") == (3, 1000)
+    for _ in range(3):
+        assert rate_limit.check_rate_limit("g1", "4.4.4.4", now=0.0) is None
+    assert rate_limit.check_rate_limit("g1", "4.4.4.4", now=0.0) == 600
+
+
+def test_an_invalid_limit_keeps_the_default(monkeypatch: pytest.MonkeyPatch) -> None:
+    monkeypatch.setenv("RATE_LIMIT_ROUTES_GUEST", "lots")
+    monkeypatch.setenv("RATE_LIMIT_ROUTES_IP", "0")
+    assert rate_limit.limits_for("routes") == (60, 180)
+
+
+def test_explicit_limits_win_over_the_environment(fake_redis, monkeypatch: pytest.MonkeyPatch) -> None:
+    monkeypatch.setenv("RATE_LIMIT_CHAT_GUEST", "1000")
+    assert rate_limit.check_rate_limit("g1", "5.5.5.5", now=0.0, guest_limit=1, ip_limit=50) is None
+    assert rate_limit.check_rate_limit("g1", "5.5.5.5", now=0.0, guest_limit=1, ip_limit=50) == 600
+
+
+def test_an_unknown_bucket_uses_the_chat_limits() -> None:
+    assert rate_limit.limits_for("something-else") == rate_limit.limits_for("chat")
diff --git a/backend/tests/test_routes_router.py b/backend/tests/test_routes_router.py
index de6e7a7..320503f 100644
--- a/backend/tests/test_routes_router.py
+++ b/backend/tests/test_routes_router.py
@@ -132,11 +132,7 @@ def test_guests_are_counted_in_the_routes_bucket(_defaults) -> None:
     with patch.object(routes.routing, "routes_for", AsyncMock(return_value=[_found("a", 5), _found("b", 6)])):
         _client().post("/routes", json=BODY)
     assert _defaults.call_args.args[0] == GUEST
-    assert _defaults.call_args.kwargs == {
-        "bucket": "routes",
-        "guest_limit": routes.ROUTES_GUEST_LIMIT,
-        "ip_limit": routes.ROUTES_IP_LIMIT,
-    }
+    assert _defaults.call_args.kwargs == {"bucket": "routes"}
 
 
 def test_signed_in_users_are_not_rate_limited(_defaults, monkeypatch: pytest.MonkeyPatch) -> None:
```

**Step 2 — the tests fail without the code.** `pytest tests/test_rate_limit.py tests/test_routes_router.py -q` ends with `5 failed, 25 passed in 0.43s`:

```text
E       AttributeError: module 'services.rate_limit' has no attribute 'limits_for'
E       AttributeError: module 'services.rate_limit' has no attribute 'limits_for'
E       AssertionError: assert {'bucket': 'r...p_limit': 180} == {'bucket': 'routes'}
E         
```

**Step 3 — the code.**

```diff
diff --git a/backend/routers/routes.py b/backend/routers/routes.py
index 30fd051..619a0b7 100644
--- a/backend/routers/routes.py
+++ b/backend/routers/routes.py
@@ -8,13 +8,7 @@ from cache import get_cached_facilities
 from middleware.auth import get_actor
 from models import RoutesRequest, RoutesResponse
 from services import routing
-from services.rate_limit import (
-    ROUTES_GUEST_LIMIT,
-    ROUTES_IP_LIMIT,
-    busy_response,
-    check_rate_limit,
-    client_ip,
-)
+from services.rate_limit import busy_response, check_rate_limit, client_ip
 
 router = APIRouter(tags=["routes"])
 
@@ -32,8 +26,6 @@ async def post_routes(
             str(actor.id),  # type: ignore[attr-defined]
             client_ip(request),
             bucket="routes",
-            guest_limit=ROUTES_GUEST_LIMIT,
-            ip_limit=ROUTES_IP_LIMIT,
         )
         if retry_after is not None:
             return busy_response(retry_after)
diff --git a/backend/services/rate_limit.py b/backend/services/rate_limit.py
index 02bfa04..79061fb 100644
--- a/backend/services/rate_limit.py
+++ b/backend/services/rate_limit.py
@@ -12,6 +12,7 @@ import sentry_sdk
 from fastapi.responses import JSONResponse
 from starlette.requests import Request
 
+from config import env_int
 from services.wait_times import redis_client
 
 logger = logging.getLogger(__name__)
@@ -35,16 +36,36 @@ def client_ip(request: Request) -> str:
     return request.client.host if request.client else "unknown"
 
 
+# bucket -> (guest setting, guest default, IP setting, IP default)
+_BUCKET_SETTINGS: dict[str, tuple[str, int, str, int]] = {
+    "chat": ("RATE_LIMIT_CHAT_GUEST", GUEST_LIMIT, "RATE_LIMIT_CHAT_IP", IP_LIMIT),
+    "routes": ("RATE_LIMIT_ROUTES_GUEST", ROUTES_GUEST_LIMIT, "RATE_LIMIT_ROUTES_IP", ROUTES_IP_LIMIT),
+}
+
+
+def limits_for(bucket: str) -> tuple[int, int]:
+    """(guest limit, IP limit) for a bucket: the constants above unless the environment overrides
+    them. The overrides exist for load tests on staging; guests keep the defaults."""
+    guest_setting, guest_default, ip_setting, ip_default = _BUCKET_SETTINGS.get(bucket, _BUCKET_SETTINGS["chat"])
+    return env_int(guest_setting, guest_default), env_int(ip_setting, ip_default)
+
+
 def check_rate_limit(
     guest_id: str,
     ip: str,
     now: float | None = None,
     *,
     bucket: str = "chat",
-    guest_limit: int = GUEST_LIMIT,
-    ip_limit: int = IP_LIMIT,
+    guest_limit: int | None = None,
+    ip_limit: int | None = None,
 ) -> int | None:
-    """Counts this request in `bucket`. Returns seconds until the window ends when over a limit, else None."""
+    """Counts this request in `bucket`. Returns seconds until the window ends when over a limit, else None.
+
+    Limits come from `limits_for(bucket)` unless passed explicitly.
+    """
+    default_guest_limit, default_ip_limit = limits_for(bucket)
+    guest_limit = default_guest_limit if guest_limit is None else guest_limit
+    ip_limit = default_ip_limit if ip_limit is None else ip_limit
     now = time.time() if now is None else now
     window = int(now // WINDOW_SECONDS)
     ip_hash = hashlib.sha256(ip.encode()).hexdigest()[:32]
```

**Step 4 — the tests pass.** `pytest tests/test_rate_limit.py tests/test_routes_router.py -q` ends with `30 passed in 0.27s`.

### Task 4: Routing and graph timing

**Commit:** `feat: time routing calls and graph lookups`

**Files:**
- Modify: `backend/graph/base.py`
- Modify: `backend/services/routing.py`
- Modify: `backend/tests/graph/test_base.py`
- Modify: `backend/tests/test_routing.py`

**Interfaces:** Consumes: `metrics.timed`, `ROUTING_CALL_DURATION`, `GRAPH_LOOKUP_DURATION` (Task 1). Produces: one observation per Geoapify call (labels `mode`, `outcome`) and per graph lookup (labels `provider`, `outcome`); `routing_candidate_failed` log lines gain a `status` field.

**Step 1 — tests first.**

```diff
diff --git a/backend/tests/graph/test_base.py b/backend/tests/graph/test_base.py
index eb8c4ec..5266245 100644
--- a/backend/tests/graph/test_base.py
+++ b/backend/tests/graph/test_base.py
@@ -24,3 +24,31 @@ def test_null_provider_always_returns_empty_context():
 
 def test_graph_context_default_red_flags_is_empty_list():
     assert GraphContext(matched=False).red_flags == []
+
+
+def _graph_count(provider: str, outcome: str) -> float:
+    from observability import _registry
+    return _registry.get_sample_value(
+        "graph_lookup_duration_seconds_count", {"provider": provider, "outcome": outcome}
+    ) or 0.0
+
+
+def test_lookup_is_timed_under_the_configured_provider_name(monkeypatch):
+    monkeypatch.setenv("GRAPH_RAG_PROVIDER", "Static")
+    before = _graph_count("static", "ok")
+    NullGraphProvider().get_symptom_graph_context("chest pain", [])
+    assert _graph_count("static", "ok") == before + 1
+
+
+def test_lookup_defaults_to_the_off_label(monkeypatch):
+    monkeypatch.delenv("GRAPH_RAG_PROVIDER", raising=False)
+    before = _graph_count("off", "ok")
+    NullGraphProvider().get_symptom_graph_context("chest pain", [])
+    assert _graph_count("off", "ok") == before + 1
+
+
+def test_failed_lookup_is_timed_as_an_error(monkeypatch):
+    monkeypatch.setenv("GRAPH_RAG_PROVIDER", "neo4j")
+    before = _graph_count("neo4j", "error")
+    _ExplodingProvider().get_symptom_graph_context("chest pain", [])
+    assert _graph_count("neo4j", "error") == before + 1
diff --git a/backend/tests/test_routing.py b/backend/tests/test_routing.py
index fa078ec..c711744 100644
--- a/backend/tests/test_routing.py
+++ b/backend/tests/test_routing.py
@@ -146,3 +146,52 @@ def test_fastest_ignores_candidates_without_a_route_and_can_be_none() -> None:
     assert routing.fastest_facility_id([_route("a", None), _route("b", 30)]) == "b"
     assert routing.fastest_facility_id([_route("a", None)]) is None
     assert routing.fastest_facility_id([]) is None
+
+
+from observability import _registry
+
+
+def _routing_count(mode: str, outcome: str) -> float:
+    return _registry.get_sample_value("routing_call_duration_seconds_count", {"mode": mode, "outcome": outcome}) or 0.0
+
+
+@pytest.mark.asyncio
+async def test_each_candidate_call_is_timed_with_its_outcome() -> None:
+    def handler(request: httpx.Request) -> httpx.Response:
+        waypoints = request.url.params["waypoints"]
+        if "43.7224" in waypoints:
+            return httpx.Response(500, json={"error": "boom"})
+        if "43.7557" in waypoints:
+            return httpx.Response(200, json={"features": []})
+        return httpx.Response(200, json=_feature(600, 5000, LINE))
+
+    before = {o: _routing_count("bike", o) for o in ("ok", "error", "no_route", "timeout")}
+    await routing.routes_for(ORIGIN, [A, B, C], "bike", transport=_transport(handler))
+
+    assert _routing_count("bike", "ok") == before["ok"] + 1
+    assert _routing_count("bike", "error") == before["error"] + 1
+    assert _routing_count("bike", "no_route") == before["no_route"] + 1
+    assert _routing_count("bike", "timeout") == before["timeout"]
+
+
+@pytest.mark.asyncio
+async def test_a_timeout_is_recorded_as_a_timeout() -> None:
+    def handler(request: httpx.Request) -> httpx.Response:
+        raise httpx.ReadTimeout("slow", request=request)
+
+    before = _routing_count("walk", "timeout")
+    await routing.routes_for(ORIGIN, [A], "walk", transport=_transport(handler))
+    assert _routing_count("walk", "timeout") == before + 1
+
+
+@pytest.mark.asyncio
+async def test_a_provider_status_code_is_logged_without_the_key(caplog: pytest.LogCaptureFixture) -> None:
+    def handler(request: httpx.Request) -> httpx.Response:
+        return httpx.Response(400, json={"message": f"no route, key {KEY}"})
+
+    with caplog.at_level(logging.WARNING):
+        await routing.routes_for(ORIGIN, [A], "car", transport=_transport(handler))
+
+    failed = [rec for rec in caplog.records if rec.getMessage() == "routing_candidate_failed"]
+    assert [(rec.error_type, rec.status) for rec in failed] == [("HTTPStatusError", 400)]
+    assert KEY not in str(failed[0].__dict__)
```

**Step 2 — the tests fail without the code.** `pytest tests/graph/test_base.py tests/test_routing.py -q` ends with `6 failed, 18 passed in 0.30s`:

```text
E       AssertionError: assert 0.0 == (0.0 + 1)
E        +  where 0.0 = _routing_count('walk', 'timeout')
E       AttributeError: 'LogRecord' object has no attribute 'status'
FAILED tests/graph/test_base.py::test_lookup_is_timed_under_the_configured_provider_name
```

**Step 3 — the code.**

```diff
diff --git a/backend/graph/base.py b/backend/graph/base.py
index 489be51..1d50020 100644
--- a/backend/graph/base.py
+++ b/backend/graph/base.py
@@ -4,9 +4,12 @@ deferred v2 (Neo4j) implementation satisfy. Mirrors BaseLLMClient
 (backend/llm/base.py). See design §3.
 """
 import logging
+import os
 from abc import ABC, abstractmethod
 from dataclasses import dataclass, field
 
+from metrics import GRAPH_LOOKUP_DURATION, timed
+
 logger = logging.getLogger(__name__)
 
 
@@ -38,14 +41,19 @@ class GraphContextProvider(ABC):
         dependency (unlike BaseLLMClient or find_nearest_facilities, which can
         surface a 503). Any failure in a subclass's _lookup() degrades to an
         empty GraphContext, logged but never propagated."""
-        try:
-            return self._lookup(user_message, recent_messages)
-        except Exception:
-            logger.exception(
-                "graph_context_lookup_failed",
-                extra={"provider": type(self).__name__},
-            )
-            return GraphContext(matched=False)
+        # Labelled with the configured provider name (off, static, neo4j), not the class name, so
+        # the series stays the same when an implementation is renamed.
+        provider = os.environ.get("GRAPH_RAG_PROVIDER", "off").lower()
+        with timed(GRAPH_LOOKUP_DURATION, provider=provider) as timing:
+            try:
+                return self._lookup(user_message, recent_messages)
+            except Exception:
+                timing.outcome = "error"
+                logger.exception(
+                    "graph_context_lookup_failed",
+                    extra={"provider": type(self).__name__},
+                )
+                return GraphContext(matched=False)
 
     @abstractmethod
     def _lookup(self, user_message: str, recent_messages: list[str]) -> GraphContext:
diff --git a/backend/services/routing.py b/backend/services/routing.py
index 8098f8d..3d61f53 100644
--- a/backend/services/routing.py
+++ b/backend/services/routing.py
@@ -13,6 +13,8 @@ import os
 
 import httpx
 
+from metrics import ROUTING_CALL_DURATION, timed
+
 logger = logging.getLogger(__name__)
 # httpx logs every request URL at INFO, and the Geoapify key is in the query string.
 logging.getLogger("httpx").setLevel(logging.WARNING)
@@ -63,22 +65,27 @@ async def _fetch_route(
         "mode": GEOAPIFY_MODES[mode],
         "apiKey": key,
     }
-    try:
-        response = await client.get(GEOAPIFY_ROUTING_URL, params=params)
-        response.raise_for_status()
-        parsed = parse_route(response.json())
-    except (httpx.HTTPError, ValueError, TypeError, KeyError, IndexError) as exc:
-        _log_failure(mode, facility, type(exc).__name__)
-        return None
-    if parsed is None:
-        _log_failure(mode, facility, "NoRoute")
-    return parsed
-
-
-def _log_failure(mode: str, facility: dict, error_type: str) -> None:
+    with timed(ROUTING_CALL_DURATION, mode=mode) as timing:
+        try:
+            response = await client.get(GEOAPIFY_ROUTING_URL, params=params)
+            response.raise_for_status()
+            parsed = parse_route(response.json())
+        except (httpx.HTTPError, ValueError, TypeError, KeyError, IndexError) as exc:
+            timing.outcome = "timeout" if isinstance(exc, httpx.TimeoutException) else "error"
+            status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
+            _log_failure(mode, facility, type(exc).__name__, status)
+            return None
+        if parsed is None:
+            timing.outcome = "no_route"
+            _log_failure(mode, facility, "NoRoute")
+        return parsed
+
+
+def _log_failure(mode: str, facility: dict, error_type: str, status: int | None = None) -> None:
+    # The provider's status code is safe to log; its message and URL are not (the key is in the URL).
     logger.warning(
         "routing_candidate_failed",
-        extra={"mode": mode, "facility_id": str(facility["id"]), "error_type": error_type},
+        extra={"mode": mode, "facility_id": str(facility["id"]), "error_type": error_type, "status": status},
     )
 
 
```

**Step 4 — the tests pass.** `pytest tests/graph/test_base.py tests/test_routing.py -q` ends with `24 passed in 0.19s`.

### Task 5: Grafana push removed, `/metrics` closed without a token

**Commit:** `fix: remove the broken grafana push and close metrics without a token`

**Files:**
- Modify: `backend/observability.py`
- Create: `backend/tests/test_observability_metrics.py`

**Interfaces:** Produces: `observability.init_metrics` starts no thread; `verify_metrics_token` answers 503 when `METRICS_BEARER_TOKEN` is unset or blank, 403 on a wrong token.

**Step 1 — tests first.**

```diff
diff --git a/backend/tests/test_observability_metrics.py b/backend/tests/test_observability_metrics.py
new file mode 100644
index 0000000..9d3e788
--- /dev/null
+++ b/backend/tests/test_observability_metrics.py
@@ -0,0 +1,55 @@
+import os
+import sys
+import threading
+
+sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
+
+import pytest
+from fastapi import Depends, FastAPI
+from fastapi.testclient import TestClient
+
+import observability
+
+
+def _client() -> TestClient:
+    app = FastAPI()
+
+    @app.get("/metrics")
+    def metrics(_: None = Depends(observability.verify_metrics_token)) -> dict:
+        return {"ok": True}
+
+    return TestClient(app)
+
+
+def test_metrics_is_closed_when_no_token_is_configured(monkeypatch: pytest.MonkeyPatch) -> None:
+    monkeypatch.delenv("METRICS_BEARER_TOKEN", raising=False)
+    assert _client().get("/metrics").status_code == 503
+    assert _client().get("/metrics", headers={"Authorization": "Bearer anything"}).status_code == 503
+
+
+def test_a_blank_token_counts_as_not_configured(monkeypatch: pytest.MonkeyPatch) -> None:
+    monkeypatch.setenv("METRICS_BEARER_TOKEN", "   ")
+    assert _client().get("/metrics", headers={"Authorization": "Bearer    "}).status_code == 503
+
+
+def test_metrics_rejects_a_missing_or_wrong_token(monkeypatch: pytest.MonkeyPatch) -> None:
+    monkeypatch.setenv("METRICS_BEARER_TOKEN", "s3cret")
+    assert _client().get("/metrics").status_code == 403
+    assert _client().get("/metrics", headers={"Authorization": "Bearer nope"}).status_code == 403
+    assert _client().get("/metrics", headers={"Authorization": "s3cret"}).status_code == 403
+
+
+def test_metrics_accepts_the_configured_token(monkeypatch: pytest.MonkeyPatch) -> None:
+    monkeypatch.setenv("METRICS_BEARER_TOKEN", "s3cret")
+    assert _client().get("/metrics", headers={"Authorization": "Bearer s3cret"}).status_code == 200
+
+
+def test_init_metrics_starts_no_background_thread(monkeypatch: pytest.MonkeyPatch) -> None:
+    # The Grafana variables used to start a push thread; they must have no effect any more.
+    monkeypatch.setenv("GRAFANA_PROMETHEUS_REMOTE_WRITE_URL", "https://example.invalid/push")
+    monkeypatch.setenv("GRAFANA_PROMETHEUS_INSTANCE_ID", "1")
+    monkeypatch.setenv("GRAFANA_API_TOKEN", "t")
+    before = threading.active_count()
+    observability.init_metrics(FastAPI())
+    assert threading.active_count() == before
+    assert not hasattr(observability, "push_to_gateway")
```

**Step 2 — the tests fail without the code.** `pytest tests/test_observability_metrics.py -q` ends with `3 failed, 2 passed in 0.26s`:

```text
E        +      where get = <starlette.testclient.TestClient object at 0x727bd4b3f320>.get
E        +        where <starlette.testclient.TestClient object at 0x727bd4b3f320> = _client()
E       AssertionError: assert 200 == 503
E        +  where 200 = <Response [200 OK]>.status_code
```

**Step 3 — the code.**

```diff
diff --git a/backend/observability.py b/backend/observability.py
index eb6b351..95f8314 100644
--- a/backend/observability.py
+++ b/backend/observability.py
@@ -1,14 +1,12 @@
 import logging
 import os
-import threading
-import time
 import uuid
 
 logger = logging.getLogger(__name__)
 
 import sentry_sdk
 from fastapi import Header, HTTPException
-from prometheus_client import CollectorRegistry, push_to_gateway
+from prometheus_client import CollectorRegistry
 from prometheus_fastapi_instrumentator import Instrumentator
 from pythonjsonlogger import jsonlogger
 from sentry_sdk.integrations.fastapi import FastApiIntegration
@@ -63,48 +61,18 @@ def init_metrics(app) -> Instrumentator:  # type: ignore[type-arg]
     instrumentator = Instrumentator(registry=_registry)
     instrumentator.instrument(app)
 
-    remote_write_url = os.environ.get("GRAFANA_PROMETHEUS_REMOTE_WRITE_URL")
-    instance_id = os.environ.get("GRAFANA_PROMETHEUS_INSTANCE_ID")
-    api_token = os.environ.get("GRAFANA_API_TOKEN")
-
-    if not all([remote_write_url, instance_id, api_token]):
-        logger.warning("metrics_push_disabled", extra={"reason": "Grafana Prometheus vars not set"})
-        return instrumentator
-
-    def push_loop() -> None:
-        while True:
-            try:
-                push_to_gateway(
-                    remote_write_url,
-                    job="medicoord-api",
-                    registry=_registry,
-                    handler=lambda url, method, timeout, headers, data: (
-                        __import__("requests").request(
-                            method,
-                            url,
-                            data=data,
-                            headers={
-                                **dict(headers),
-                                "Authorization": "Bearer " + api_token,  # type: ignore[operator]
-                            },
-                            timeout=timeout,
-                        )
-                    ),
-                )
-            except Exception as exc:
-                logging.getLogger(__name__).warning(
-                    "Metrics push failed", extra={"error": str(exc)}
-                )
-            time.sleep(30)
-
-    thread = threading.Thread(target=push_loop, daemon=True)
-    thread.start()
+    # Metrics are pulled, not pushed: Grafana Cloud scrapes GET /metrics (Metrics Endpoint
+    # integration, Bearer METRICS_BEARER_TOKEN). The push thread that used to live here never
+    # delivered a sample.
     return instrumentator
 
 
 def verify_metrics_token(authorization: str = Header(default="")) -> None:
-    token = os.environ.get("METRICS_BEARER_TOKEN")
-    if token and authorization != f"Bearer {token}":
+    token = os.environ.get("METRICS_BEARER_TOKEN", "").strip()
+    if not token:
+        # Fail closed: without a configured token the endpoint would be open to anyone.
+        raise HTTPException(status_code=503, detail="Metrics token not configured")
+    if authorization != f"Bearer {token}":
         raise HTTPException(status_code=403, detail="Forbidden")
 
 
```

**Step 4 — the tests pass.** `pytest tests/test_observability_metrics.py -q` ends with `5 passed in 0.17s`.


---

# Part 2 — LLM providers

### Task 6: LLM call instrumentation and error classification

**Commit:** `feat: time and count llm provider calls and classify their failures`

**Files:**
- Create: `backend/llm/instrumented.py`
- Create: `backend/tests/llm/test_instrumented.py`

**Interfaces:** Consumes: `metrics.timed`, `LLM_CALL_DURATION`, `LLM_CALLS`, `LLM_TOKENS` (Task 1). Produces: `llm.instrumented.classify_llm_error(exc) -> str`, `worth_trying_another_provider(exc) -> bool`, `InstrumentedLLMClient(inner, provider)` with a public `provider` attribute.

**Step 1 — tests first.**

```diff
diff --git a/backend/tests/llm/test_instrumented.py b/backend/tests/llm/test_instrumented.py
new file mode 100644
index 0000000..082b79c
--- /dev/null
+++ b/backend/tests/llm/test_instrumented.py
@@ -0,0 +1,163 @@
+import os
+import sys
+
+sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))
+
+import pytest
+
+from llm.base import BaseLLMClient, LLMMessage, LLMResponse
+from llm.instrumented import InstrumentedLLMClient, classify_llm_error, worth_trying_another_provider
+from observability import _registry
+
+
+class _StatusError(Exception):
+    def __init__(self, status_code: int) -> None:
+        super().__init__(f"status {status_code}")
+        self.status_code = status_code
+
+
+class APITimeoutError(Exception):
+    """Same name as the SDK timeout classes; the classifier goes by name."""
+
+
+class APIConnectionError(Exception):
+    """Same name as the SDK connection-failure classes."""
+
+
+@pytest.mark.parametrize("exc,expected", [
+    (_StatusError(429), "rate_limited"),
+    (APITimeoutError("slow"), "timeout"),
+    (TimeoutError("slow"), "timeout"),
+    (_StatusError(503), "error"),
+    (_StatusError(400), "error"),
+    (ValueError("bad json"), "error"),
+])
+def test_classify_llm_error(exc: Exception, expected: str) -> None:
+    assert classify_llm_error(exc) == expected
+
+
+@pytest.mark.parametrize("exc,expected", [
+    (_StatusError(429), True),
+    (APITimeoutError("slow"), True),
+    (_StatusError(500), True),
+    (_StatusError(503), True),
+    (APIConnectionError("dns"), True),
+    (ConnectionResetError("reset"), True),
+    (_StatusError(401), True),
+    (_StatusError(403), True),
+    (_StatusError(400), False),
+    (_StatusError(404), False),
+    (_StatusError(422), False),
+    (ValueError("bad json"), False),
+    (KeyError("choices"), False),
+])
+def test_worth_trying_another_provider(exc: Exception, expected: bool) -> None:
+    assert worth_trying_another_provider(exc) is expected
+
+
+class _Fake(BaseLLMClient):
+    def __init__(self, result: object) -> None:
+        self.result = result
+        self.calls: list[dict] = []
+
+    @property
+    def model_name(self) -> str:
+        return "fake-model"
+
+    def chat(self, messages, tools=None, temperature=0.2, stop=None, force_tool=None) -> LLMResponse:
+        self.calls.append({"messages": messages, "tools": tools, "temperature": temperature,
+                           "stop": stop, "force_tool": force_tool})
+        if isinstance(self.result, Exception):
+            raise self.result
+        return self.result  # type: ignore[return-value]
+
+
+def _response(prompt: int = 11, completion: int = 5) -> LLMResponse:
+    return LLMResponse(content="hi", tool_calls=None, finish_reason="stop", model="fake-model",
+                       usage={"prompt_tokens": prompt, "completion_tokens": completion})
+
+
+def _value(name: str, **labels: str) -> float:
+    return _registry.get_sample_value(name, labels) or 0.0
+
+
+MESSAGES = [LLMMessage(role="user", content="hello")]
+
+
+def test_a_successful_call_is_timed_counted_and_its_tokens_added() -> None:
+    labels = {"provider": "probe-ok", "outcome": "ok"}
+    client = InstrumentedLLMClient(_Fake(_response(prompt=11, completion=5)), "probe-ok")
+
+    assert client.chat(MESSAGES).content == "hi"
+
+    assert _value("llm_calls_total", **labels) == 1
+    assert _value("llm_call_duration_seconds_count", **labels) == 1
+    assert _value("llm_tokens_total", provider="probe-ok", kind="prompt") == 11
+    assert _value("llm_tokens_total", provider="probe-ok", kind="completion") == 5
+
+
+@pytest.mark.parametrize("exc,outcome", [
+    (_StatusError(429), "rate_limited"),
+    (APITimeoutError("slow"), "timeout"),
+    (_StatusError(500), "error"),
+])
+def test_a_failed_call_is_counted_under_its_outcome_and_re_raised(exc: Exception, outcome: str) -> None:
+    provider = f"probe-{outcome}"
+    client = InstrumentedLLMClient(_Fake(exc), provider)
+
+    with pytest.raises(type(exc)) as caught:
+        client.chat(MESSAGES)
+
+    assert caught.value is exc
+    assert _value("llm_calls_total", provider=provider, outcome=outcome) == 1
+    assert _value("llm_call_duration_seconds_count", provider=provider, outcome=outcome) == 1
+    assert _value("llm_calls_total", provider=provider, outcome="ok") == 0
+    assert _value("llm_tokens_total", provider=provider, kind="prompt") == 0
+
+
+def test_arguments_and_model_name_pass_through_unchanged() -> None:
+    inner = _Fake(_response())
+    client = InstrumentedLLMClient(inner, "probe-args")
+    client.chat(MESSAGES, tools=["t"], temperature=0.7, stop=["END"], force_tool="triage_response")  # type: ignore[list-item]
+    assert inner.calls == [{"messages": MESSAGES, "tools": ["t"], "temperature": 0.7,
+                            "stop": ["END"], "force_tool": "triage_response"}]
+    assert client.model_name == "fake-model" and client.provider == "probe-args"
+
+
+def test_missing_usage_does_not_break_the_call() -> None:
+    response = _response()
+    response.usage = {}
+    assert InstrumentedLLMClient(_Fake(response), "probe-nousage").chat(MESSAGES) is response
+
+
+def _sdk_errors(module) -> dict[str, Exception]:
+    import httpx
+
+    request = httpx.Request("POST", "https://provider.invalid/v1/chat")
+
+    def status(cls, code: int) -> Exception:
+        return cls("boom", response=httpx.Response(code, request=request), body=None)
+
+    return {
+        "rate_limit": status(module.RateLimitError, 429),
+        "server": status(module.InternalServerError, 500),
+        "bad_request": status(module.BadRequestError, 400),
+        "auth": status(module.AuthenticationError, 401),
+        "timeout": module.APITimeoutError(request=request),
+        "connection": module.APIConnectionError(request=request),
+    }
+
+
+@pytest.mark.parametrize("sdk_name", ["groq", "openai", "anthropic"])
+def test_real_sdk_exceptions_are_classified_as_expected(sdk_name: str) -> None:
+    import importlib
+
+    errors = _sdk_errors(importlib.import_module(sdk_name))
+    assert {name: classify_llm_error(exc) for name, exc in errors.items()} == {
+        "rate_limit": "rate_limited", "server": "error", "bad_request": "error",
+        "auth": "error", "timeout": "timeout", "connection": "error",
+    }
+    assert {name: worth_trying_another_provider(exc) for name, exc in errors.items()} == {
+        "rate_limit": True, "server": True, "bad_request": False,
+        "auth": True, "timeout": True, "connection": True,
+    }
```

**Step 2 — the tests fail without the code.** `pytest tests/llm/test_instrumented.py -q` ends with `1 error in 0.22s`:

```text
E   ModuleNotFoundError: No module named 'llm.instrumented'
ERROR tests/llm/test_instrumented.py
```

**Step 3 — the code.**

```diff
diff --git a/backend/llm/instrumented.py b/backend/llm/instrumented.py
new file mode 100644
index 0000000..63c9d50
--- /dev/null
+++ b/backend/llm/instrumented.py
@@ -0,0 +1,73 @@
+"""Timing and outcome counting for any LLM provider client, and the one place that decides what
+kind of failure a provider error is.
+
+Provider clients stay free of metric code: the factory wraps each of them in
+InstrumentedLLMClient. The classifier reads only `status_code` and exception class names, which
+the Groq, OpenAI and Anthropic SDKs all expose, so this module imports none of them.
+"""
+from metrics import LLM_CALL_DURATION, LLM_CALLS, LLM_TOKENS, timed
+
+from .base import BaseLLMClient, LLMMessage, LLMResponse, ToolDefinition
+
+
+def _class_names(exc: BaseException) -> set[str]:
+    return {cls.__name__ for cls in type(exc).__mro__}
+
+
+def classify_llm_error(exc: BaseException) -> str:
+    """rate_limited, timeout or error: the outcome label for a failed provider call."""
+    if getattr(exc, "status_code", None) == 429:
+        return "rate_limited"
+    if isinstance(exc, TimeoutError) or any("Timeout" in name for name in _class_names(exc)):
+        return "timeout"
+    return "error"
+
+
+def worth_trying_another_provider(exc: BaseException) -> bool:
+    """True when the failure belongs to this provider: rate limit, timeout, its server, the
+    connection to it, or its credentials (a revoked key must not take the chat down while another
+    provider works). False for a request another provider would reject too."""
+    if classify_llm_error(exc) in ("rate_limited", "timeout"):
+        return True
+    status = getattr(exc, "status_code", None)
+    if isinstance(status, int):
+        return status >= 500 or status in (401, 403)
+    return isinstance(exc, ConnectionError) or any("Connection" in name for name in _class_names(exc))
+
+
+class InstrumentedLLMClient(BaseLLMClient):
+    """Wraps one provider client: every call is timed and counted under `provider`."""
+
+    def __init__(self, inner: BaseLLMClient, provider: str) -> None:
+        self._inner = inner
+        self.provider = provider
+
+    @property
+    def model_name(self) -> str:
+        return self._inner.model_name
+
+    def chat(
+        self,
+        messages: list[LLMMessage],
+        tools: list[ToolDefinition] | None = None,
+        temperature: float = 0.2,
+        stop: list[str] | None = None,
+        force_tool: str | None = None,
+    ) -> LLMResponse:
+        outcome = "ok"
+        try:
+            with timed(LLM_CALL_DURATION, provider=self.provider) as timing:
+                try:
+                    response = self._inner.chat(
+                        messages=messages, tools=tools, temperature=temperature, stop=stop, force_tool=force_tool,
+                    )
+                except Exception as exc:
+                    outcome = timing.outcome = classify_llm_error(exc)
+                    raise
+        finally:
+            LLM_CALLS.labels(provider=self.provider, outcome=outcome).inc()
+
+        usage = response.usage or {}
+        LLM_TOKENS.labels(provider=self.provider, kind="prompt").inc(usage.get("prompt_tokens") or 0)
+        LLM_TOKENS.labels(provider=self.provider, kind="completion").inc(usage.get("completion_tokens") or 0)
+        return response
```

**Step 4 — the tests pass.** `pytest tests/llm/test_instrumented.py -q` ends with `28 passed in 0.21s`.

### Task 7: OpenAI provider client

**Commit:** `feat: add an openai provider client`

**Files:**
- Create: `backend/llm/openai_client.py`
- Create: `backend/tests/llm/test_openai_client.py`

**Interfaces:** Consumes: `config.llm_timeout_seconds` (Task 1). Produces: `llm.openai_client.OpenAIClient(max_retries=None)`; raises `RuntimeError` naming the missing variable when `OPENAI_API_KEY` or `OPENAI_MODEL` is unset.

**Step 1 — tests first.**

```diff
diff --git a/backend/tests/llm/test_openai_client.py b/backend/tests/llm/test_openai_client.py
new file mode 100644
index 0000000..d0e572a
--- /dev/null
+++ b/backend/tests/llm/test_openai_client.py
@@ -0,0 +1,120 @@
+import os
+import sys
+
+sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))
+
+from unittest.mock import MagicMock, patch
+
+import pytest
+
+from llm.base import LLMMessage
+from llm.tools import TRIAGE_RESPONSE
+
+
+@pytest.fixture(autouse=True)
+def _env(monkeypatch: pytest.MonkeyPatch) -> None:
+    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
+    monkeypatch.setenv("OPENAI_MODEL", "test-model")
+    monkeypatch.delenv("LLM_TIMEOUT_SECONDS", raising=False)
+
+
+def _completion(content: str | None = "hello", tool_calls: list | None = None, finish_reason: str = "stop"):
+    return MagicMock(
+        choices=[MagicMock(finish_reason=finish_reason, message=MagicMock(content=content, tool_calls=tool_calls))],
+        usage=MagicMock(prompt_tokens=21, completion_tokens=8),
+    )
+
+
+def _tool_call():
+    function = MagicMock(arguments='{"severity": "urgent"}')
+    function.name = "triage_response"  # MagicMock(name=...) sets repr, not the attribute
+    return MagicMock(id="tc1", function=function)
+
+
+def _client(completion=None):
+    from llm.openai_client import OpenAIClient
+
+    with patch("llm.openai_client.OpenAI") as sdk:
+        sdk.return_value.chat.completions.create.return_value = completion or _completion()
+        client = OpenAIClient()
+    return client, sdk
+
+
+def test_plain_text_request_and_response() -> None:
+    client, sdk = _client()
+    resp = client.chat(messages=[LLMMessage(role="system", content="be brief"), LLMMessage(role="user", content="hi")])
+
+    sent = sdk.return_value.chat.completions.create.call_args.kwargs
+    assert sent == {
+        "model": "test-model",
+        "messages": [{"role": "system", "content": "be brief"}, {"role": "user", "content": "hi"}],
+        "temperature": 0.2,
+    }
+    assert (resp.content, resp.tool_calls, resp.finish_reason, resp.model) == ("hello", None, "stop", "test-model")
+    assert resp.usage == {"prompt_tokens": 21, "completion_tokens": 8}
+
+
+def test_tools_are_sent_with_auto_choice_and_stop_sequences() -> None:
+    client, sdk = _client()
+    client.chat(messages=[LLMMessage(role="user", content="hi")], tools=[TRIAGE_RESPONSE], stop=["END"], temperature=0.0)
+
+    sent = sdk.return_value.chat.completions.create.call_args.kwargs
+    assert sent["tool_choice"] == "auto" and sent["stop"] == ["END"] and sent["temperature"] == 0.0
+    function = sent["tools"][0]["function"]
+    assert sent["tools"][0]["type"] == "function" and function["name"] == TRIAGE_RESPONSE.name
+    assert function["parameters"] == {
+        "type": "object", "properties": TRIAGE_RESPONSE.parameters, "required": TRIAGE_RESPONSE.required,
+    }
+
+
+def test_a_forced_tool_is_named_in_tool_choice() -> None:
+    client, sdk = _client()
+    client.chat(messages=[LLMMessage(role="user", content="hi")], tools=[TRIAGE_RESPONSE], force_tool="triage_response")
+    sent = sdk.return_value.chat.completions.create.call_args.kwargs
+    assert sent["tool_choice"] == {"type": "function", "function": {"name": "triage_response"}}
+
+
+def test_tool_calls_are_read_even_when_finish_reason_is_stop() -> None:
+    # OpenAI reports "stop" for a forced tool call; the call itself is the signal.
+    client, _ = _client(_completion(content=None, tool_calls=[_tool_call()], finish_reason="stop"))
+    resp = client.chat(messages=[LLMMessage(role="user", content="hi")], tools=[TRIAGE_RESPONSE])
+    assert resp.tool_calls == [{"id": "tc1", "name": "triage_response", "arguments": '{"severity": "urgent"}'}]
+    assert resp.content is None
+
+
+def test_tool_result_messages_keep_their_call_id_and_name() -> None:
+    client, sdk = _client()
+    client.chat(messages=[LLMMessage(role="tool", content="{}", tool_call_id="tc1", name="triage_response")])
+    assert sdk.return_value.chat.completions.create.call_args.kwargs["messages"] == [
+        {"role": "tool", "content": "{}", "tool_call_id": "tc1", "name": "triage_response"}
+    ]
+
+
+def test_the_sdk_gets_the_timeout_and_keeps_its_own_retries_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
+    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "12")
+    _, sdk = _client()
+    assert sdk.call_args.kwargs == {"api_key": "test-key", "timeout": 12}
+
+
+def test_retries_can_be_turned_off_for_a_fallback_chain() -> None:
+    from llm.openai_client import OpenAIClient
+
+    with patch("llm.openai_client.OpenAI") as sdk:
+        OpenAIClient(max_retries=0)
+    assert sdk.call_args.kwargs == {"api_key": "test-key", "timeout": 30, "max_retries": 0}
+
+
+@pytest.mark.parametrize("missing", ["OPENAI_API_KEY", "OPENAI_MODEL"])
+def test_a_missing_key_or_model_is_refused(monkeypatch: pytest.MonkeyPatch, missing: str) -> None:
+    from llm.openai_client import OpenAIClient
+
+    monkeypatch.delenv(missing)
+    with patch("llm.openai_client.OpenAI"), pytest.raises(RuntimeError, match=missing):
+        OpenAIClient()
+
+
+def test_a_provider_error_is_not_swallowed() -> None:
+    client, sdk = _client()
+    sdk.return_value.chat.completions.create.side_effect = RuntimeError("boom")
+    with pytest.raises(RuntimeError, match="boom"):
+        client.chat(messages=[LLMMessage(role="user", content="hi")])
```

**Step 2 — the tests fail without the code.** `pytest tests/llm/test_openai_client.py -q` ends with `10 failed in 0.23s`:

```text
E       ModuleNotFoundError: No module named 'llm.openai_client'
E       ModuleNotFoundError: No module named 'llm.openai_client'
FAILED tests/llm/test_openai_client.py::test_plain_text_request_and_response
FAILED tests/llm/test_openai_client.py::test_tools_are_sent_with_auto_choice_and_stop_sequences
```

**Step 3 — the code.**

```diff
diff --git a/backend/llm/openai_client.py b/backend/llm/openai_client.py
new file mode 100644
index 0000000..ada2122
--- /dev/null
+++ b/backend/llm/openai_client.py
@@ -0,0 +1,96 @@
+import os
+
+from openai import OpenAI
+
+from config import llm_timeout_seconds
+
+from .base import BaseLLMClient, LLMMessage, LLMResponse, ToolDefinition
+
+
+class OpenAIClient(BaseLLMClient):
+    """OpenAI chat completions behind the provider interface. Same request and response shape as
+    GroqClient, without the tool_use_failed retry, which is specific to Groq."""
+
+    def __init__(self, max_retries: int | None = None) -> None:
+        api_key = os.environ.get("OPENAI_API_KEY")
+        if not api_key:
+            raise RuntimeError("OPENAI_API_KEY is not set")
+        # No default model on purpose: which model answers patients is an explicit choice.
+        model = os.environ.get("OPENAI_MODEL", "").strip()
+        if not model:
+            raise RuntimeError("OPENAI_MODEL is not set")
+        options: dict = {"api_key": api_key, "timeout": llm_timeout_seconds()}
+        if max_retries is not None:
+            options["max_retries"] = max_retries
+        self._client = OpenAI(**options)
+        self._model = model
+
+    @property
+    def model_name(self) -> str:
+        return self._model
+
+    def chat(
+        self,
+        messages: list[LLMMessage],
+        tools: list[ToolDefinition] | None = None,
+        temperature: float = 0.2,
+        stop: list[str] | None = None,
+        force_tool: str | None = None,
+    ) -> LLMResponse:
+        kwargs: dict = {
+            "model": self._model,
+            "messages": [self._to_openai_message(m) for m in messages],
+            "temperature": temperature,
+        }
+        if stop:
+            kwargs["stop"] = stop
+        if tools:
+            kwargs["tools"] = [self._to_openai_tool(t) for t in tools]
+            kwargs["tool_choice"] = (
+                {"type": "function", "function": {"name": force_tool}} if force_tool else "auto"
+            )
+
+        resp = self._client.chat.completions.create(**kwargs)
+        choice = resp.choices[0]
+
+        # Read the tool calls themselves, not finish_reason: with a forced tool choice OpenAI
+        # reports "stop" while still returning the call.
+        tool_calls = None
+        if choice.message.tool_calls:
+            tool_calls = [
+                {"id": tc.id, "name": tc.function.name, "arguments": tc.function.arguments}
+                for tc in choice.message.tool_calls
+            ]
+
+        return LLMResponse(
+            content=choice.message.content,
+            tool_calls=tool_calls,
+            finish_reason=choice.finish_reason,
+            model=self._model,
+            usage={
+                "prompt_tokens": resp.usage.prompt_tokens if resp.usage else 0,
+                "completion_tokens": resp.usage.completion_tokens if resp.usage else 0,
+            },
+        )
+
+    def _to_openai_message(self, msg: LLMMessage) -> dict:
+        m: dict = {"role": msg.role, "content": msg.content or ""}
+        if msg.tool_call_id:
+            m["tool_call_id"] = msg.tool_call_id
+        if msg.name:
+            m["name"] = msg.name
+        return m
+
+    def _to_openai_tool(self, tool: ToolDefinition) -> dict:
+        return {
+            "type": "function",
+            "function": {
+                "name": tool.name,
+                "description": tool.description,
+                "parameters": {
+                    "type": "object",
+                    "properties": tool.parameters,
+                    "required": tool.required,
+                },
+            },
+        }
```

**Step 4 — the tests pass.** `pytest tests/llm/test_openai_client.py -q` ends with `10 passed in 0.05s`.

### Task 8: Ordered provider fallback

**Commit:** `feat: add an ordered fallback over llm providers`

**Files:**
- Create: `backend/llm/fallback.py`
- Create: `backend/tests/llm/test_fallback.py`

**Interfaces:** Consumes: `classify_llm_error`, `worth_trying_another_provider` (Task 6). Produces: `llm.fallback.FallbackLLMClient(clients)`; logs `llm_fallback` with `from_provider`, `to_provider`, `outcome`.

**Step 1 — tests first.**

```diff
diff --git a/backend/tests/llm/test_fallback.py b/backend/tests/llm/test_fallback.py
new file mode 100644
index 0000000..9318510
--- /dev/null
+++ b/backend/tests/llm/test_fallback.py
@@ -0,0 +1,107 @@
+import os
+import sys
+
+sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))
+
+import logging
+
+import pytest
+
+from llm.base import BaseLLMClient, LLMMessage, LLMResponse
+from llm.fallback import FallbackLLMClient
+
+
+class _StatusError(Exception):
+    def __init__(self, status_code: int) -> None:
+        super().__init__(f"status {status_code}")
+        self.status_code = status_code
+
+
+class APITimeoutError(Exception):
+    pass
+
+
+class _Fake(BaseLLMClient):
+    def __init__(self, provider: str, result: object) -> None:
+        self.provider = provider
+        self.result = result
+        self.calls = 0
+
+    @property
+    def model_name(self) -> str:
+        return f"{self.provider}-model"
+
+    def chat(self, messages, tools=None, temperature=0.2, stop=None, force_tool=None) -> LLMResponse:
+        self.calls += 1
+        if isinstance(self.result, Exception):
+            raise self.result
+        return LLMResponse(content=str(self.result), tool_calls=None, finish_reason="stop",
+                           model=self.model_name, usage={"prompt_tokens": 1, "completion_tokens": 1})
+
+
+MESSAGES = [LLMMessage(role="user", content="hello")]
+
+
+def test_the_first_provider_answers_and_the_others_are_not_called() -> None:
+    first, second = _Fake("groq", "from groq"), _Fake("openai", "from openai")
+    client = FallbackLLMClient([first, second])
+    assert client.chat(MESSAGES).content == "from groq"
+    assert (first.calls, second.calls) == (1, 0)
+    assert client.model_name == "groq-model"
+
+
+@pytest.mark.parametrize("failure", [_StatusError(429), APITimeoutError("slow"), _StatusError(503),
+                                     _StatusError(401), ConnectionResetError("reset")])
+def test_a_provider_side_failure_moves_to_the_next_provider(failure: Exception) -> None:
+    first, second = _Fake("groq", failure), _Fake("openai", "from openai")
+    client = FallbackLLMClient([first, second])
+    assert client.chat(MESSAGES).content == "from openai"
+    assert (first.calls, second.calls) == (1, 1)
+    assert client.model_name == "openai-model"
+
+
+@pytest.mark.parametrize("failure", [_StatusError(400), _StatusError(422), ValueError("bad json")])
+def test_a_request_side_failure_is_raised_without_trying_another_provider(failure: Exception) -> None:
+    first, second = _Fake("groq", failure), _Fake("openai", "from openai")
+    with pytest.raises(type(failure)) as caught:
+        FallbackLLMClient([first, second]).chat(MESSAGES)
+    assert caught.value is failure
+    assert second.calls == 0
+
+
+def test_when_every_provider_fails_the_last_error_is_raised_and_each_was_tried_once() -> None:
+    first_error, last_error = _StatusError(429), _StatusError(429)
+    clients = [_Fake("groq", first_error), _Fake("openai", APITimeoutError("slow")), _Fake("anthropic", last_error)]
+    with pytest.raises(_StatusError) as caught:
+        FallbackLLMClient(clients).chat(MESSAGES)
+    assert caught.value is last_error
+    assert [c.calls for c in clients] == [1, 1, 1]
+
+
+def test_each_call_starts_again_from_the_first_provider() -> None:
+    first, second = _Fake("groq", _StatusError(429)), _Fake("openai", "from openai")
+    client = FallbackLLMClient([first, second])
+    client.chat(MESSAGES)
+    client.chat(MESSAGES)
+    assert (first.calls, second.calls) == (2, 2)
+
+
+def test_a_switch_is_logged_with_both_providers_and_the_outcome(caplog: pytest.LogCaptureFixture) -> None:
+    client = FallbackLLMClient([_Fake("groq", _StatusError(429)), _Fake("openai", "ok")])
+    with caplog.at_level(logging.WARNING):
+        client.chat(MESSAGES)
+    records = [r for r in caplog.records if r.getMessage() == "llm_fallback"]
+    assert len(records) == 1
+    assert (records[0].from_provider, records[0].to_provider, records[0].outcome) == ("groq", "openai", "rate_limited")
+
+
+def test_a_single_provider_chain_behaves_like_that_provider() -> None:
+    error = _StatusError(429)
+    with pytest.raises(_StatusError) as caught:
+        FallbackLLMClient([_Fake("groq", error)]).chat(MESSAGES)
+    assert caught.value is error
+
+
+def test_an_empty_chain_is_rejected() -> None:
+    with pytest.raises(ValueError):
+        FallbackLLMClient([])
```

**Step 2 — the tests fail without the code.** `pytest tests/llm/test_fallback.py -q` ends with `1 error in 0.21s`:

```text
E   ModuleNotFoundError: No module named 'llm.fallback'
ERROR tests/llm/test_fallback.py
```

**Step 3 — the code.**

```diff
diff --git a/backend/llm/fallback.py b/backend/llm/fallback.py
new file mode 100644
index 0000000..69e9a72
--- /dev/null
+++ b/backend/llm/fallback.py
@@ -0,0 +1,65 @@
+"""Ordered fallback over several LLM provider clients.
+
+In-process on purpose: it is the smallest thing that shows a provider failing and the next one
+answering. The intended next step is a deployed gateway that does the same job outside the API;
+this class is the seam where it would plug in.
+"""
+import logging
+
+from .base import BaseLLMClient, LLMMessage, LLMResponse, ToolDefinition
+from .instrumented import classify_llm_error, worth_trying_another_provider
+
+logger = logging.getLogger(__name__)
+
+
+def _provider_name(client: BaseLLMClient) -> str:
+    return getattr(client, "provider", type(client).__name__)
+
+
+class FallbackLLMClient(BaseLLMClient):
+    """Tries each client once, in order, until one answers.
+
+    Moves on only for failures that belong to the provider (see worth_trying_another_provider).
+    Anything else is raised at once: another provider would fail the same way, and switching
+    would hide a bug. No retry of the same provider, no sleep, no memory between calls.
+    """
+
+    def __init__(self, clients: list[BaseLLMClient]) -> None:
+        if not clients:
+            raise ValueError("FallbackLLMClient needs at least one client")
+        self._clients = clients
+        self._answered_by = clients[0]
+
+    @property
+    def model_name(self) -> str:
+        return self._answered_by.model_name
+
+    def chat(
+        self,
+        messages: list[LLMMessage],
+        tools: list[ToolDefinition] | None = None,
+        temperature: float = 0.2,
+        stop: list[str] | None = None,
+        force_tool: str | None = None,
+    ) -> LLMResponse:
+        last = len(self._clients) - 1
+        for position, client in enumerate(self._clients):
+            try:
+                response = client.chat(
+                    messages=messages, tools=tools, temperature=temperature, stop=stop, force_tool=force_tool,
+                )
+            except Exception as exc:
+                if position == last or not worth_trying_another_provider(exc):
+                    raise
+                logger.warning(
+                    "llm_fallback",
+                    extra={
+                        "from_provider": _provider_name(client),
+                        "to_provider": _provider_name(self._clients[position + 1]),
+                        "outcome": classify_llm_error(exc),
+                    },
+                )
+                continue
+            self._answered_by = client
+            return response
+        raise AssertionError("unreachable: the loop returns or raises")
```

**Step 4 — the tests pass.** `pytest tests/llm/test_fallback.py -q` ends with `14 passed in 0.16s`.

### Task 9: Client factory, timeouts and retries

**Commit:** `feat: build the llm client from a provider chain with explicit timeouts`

**Files:**
- Modify: `backend/llm/anthropic_client.py`
- Modify: `backend/llm/groq_client.py`
- Modify: `backend/services/llm_agent.py`
- Create: `backend/tests/llm/test_client_factory.py`

**Interfaces:** Consumes: `InstrumentedLLMClient` (Task 6), `OpenAIClient` (Task 7), `FallbackLLMClient` (Task 8), `config.llm_provider_chain`, `config.llm_timeout_seconds` (Task 1). Produces: `GroqClient(max_retries=None)`, `AnthropicClient(max_retries=None)`; `services.llm_agent.get_llm_client()` returns an instrumented client, or a fallback over instrumented clients when `LLM_PROVIDER_CHAIN` is set.

**Step 1 — tests first.**

```diff
diff --git a/backend/tests/llm/test_client_factory.py b/backend/tests/llm/test_client_factory.py
new file mode 100644
index 0000000..885cbf9
--- /dev/null
+++ b/backend/tests/llm/test_client_factory.py
@@ -0,0 +1,88 @@
+import os
+import sys
+
+sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))
+
+import logging
+from unittest.mock import patch
+
+import pytest
+
+from llm.anthropic_client import AnthropicClient
+from llm.fallback import FallbackLLMClient
+from llm.groq_client import GroqClient
+from llm.instrumented import InstrumentedLLMClient
+from llm.openai_client import OpenAIClient
+from services.llm_agent import get_llm_client
+
+
+@pytest.fixture(autouse=True)
+def _env(monkeypatch: pytest.MonkeyPatch):
+    for name, value in {"GROQ_API_KEY": "g", "OPENAI_API_KEY": "o", "OPENAI_MODEL": "m", "ANTHROPIC_API_KEY": "a"}.items():
+        monkeypatch.setenv(name, value)
+    for name in ("LLM_PROVIDER", "LLM_PROVIDER_CHAIN", "LLM_TIMEOUT_SECONDS"):
+        monkeypatch.delenv(name, raising=False)
+    with patch("llm.groq_client.Groq") as groq, patch("llm.openai_client.OpenAI") as openai, \
+         patch("llm.anthropic_client.anthropic.Anthropic") as anthropic:
+        yield {"groq": groq, "openai": openai, "anthropic": anthropic}
+
+
+def _providers(client: FallbackLLMClient) -> list[tuple[str, type]]:
+    return [(c.provider, type(c._inner)) for c in client._clients]  # type: ignore[attr-defined]
+
+
+def test_without_a_chain_the_default_is_one_instrumented_groq_client_with_sdk_retries(_env) -> None:
+    client = get_llm_client()
+    assert isinstance(client, InstrumentedLLMClient) and client.provider == "groq"
+    assert isinstance(client._inner, GroqClient)
+    assert _env["groq"].call_args.kwargs == {"api_key": "g", "timeout": 30}
+
+
+@pytest.mark.parametrize("name,expected", [("anthropic", AnthropicClient), ("openai", OpenAIClient),
+                                           ("GROQ", GroqClient), ("something-else", GroqClient)])
+def test_llm_provider_still_selects_the_single_client(monkeypatch: pytest.MonkeyPatch, name: str, expected: type) -> None:
+    monkeypatch.setenv("LLM_PROVIDER", name)
+    client = get_llm_client()
+    assert isinstance(client, InstrumentedLLMClient) and isinstance(client._inner, expected)
+
+
+def test_a_chain_builds_the_providers_in_order_with_sdk_retries_off(monkeypatch: pytest.MonkeyPatch, _env) -> None:
+    monkeypatch.setenv("LLM_PROVIDER_CHAIN", "groq,openai,anthropic")
+    client = get_llm_client()
+    assert isinstance(client, FallbackLLMClient)
+    assert _providers(client) == [("groq", GroqClient), ("openai", OpenAIClient), ("anthropic", AnthropicClient)]
+    for sdk in _env.values():
+        assert sdk.call_args.kwargs["max_retries"] == 0 and sdk.call_args.kwargs["timeout"] == 30
+
+
+def test_the_chain_wins_over_llm_provider(monkeypatch: pytest.MonkeyPatch) -> None:
+    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
+    monkeypatch.setenv("LLM_PROVIDER_CHAIN", "openai,groq")
+    assert _providers(get_llm_client()) == [("openai", OpenAIClient), ("groq", GroqClient)]  # type: ignore[arg-type]
+
+
+def test_unknown_names_and_providers_without_a_key_are_skipped_with_a_warning(
+    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
+) -> None:
+    monkeypatch.setenv("LLM_PROVIDER_CHAIN", "groq,mistral,openai,anthropic")
+    monkeypatch.delenv("OPENAI_MODEL")
+    with caplog.at_level(logging.WARNING):
+        client = get_llm_client()
+    assert _providers(client) == [("groq", GroqClient), ("anthropic", AnthropicClient)]  # type: ignore[arg-type]
+    skipped = [(r.provider, r.reason) for r in caplog.records if r.getMessage() == "llm_provider_skipped"]
+    assert skipped == [("mistral", "unknown provider"), ("openai", "OPENAI_MODEL is not set")]
+
+
+def test_a_chain_with_no_usable_provider_is_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
+    monkeypatch.setenv("LLM_PROVIDER_CHAIN", "mistral,openai")
+    monkeypatch.delenv("OPENAI_API_KEY")
+    with pytest.raises(RuntimeError, match="no usable provider"):
+        get_llm_client()
+
+
+def test_groq_and_anthropic_clients_take_the_timeout_from_the_environment(monkeypatch: pytest.MonkeyPatch, _env) -> None:
+    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "9")
+    GroqClient()
+    AnthropicClient(max_retries=0)
+    assert _env["groq"].call_args.kwargs == {"api_key": "g", "timeout": 9}
+    assert _env["anthropic"].call_args.kwargs == {"api_key": "a", "timeout": 9, "max_retries": 0}
```

**Step 2 — the tests fail without the code.** `pytest tests/llm/test_client_factory.py -q` ends with `10 failed in 1.05s`:

```text
E       AttributeError: 'GroqClient' object has no attribute '_clients'. Did you mean: '_client'?
E       Failed: DID NOT RAISE <class 'RuntimeError'>
E       TypeError: AnthropicClient.__init__() got an unexpected keyword argument 'max_retries'
FAILED tests/llm/test_client_factory.py::test_without_a_chain_the_default_is_one_instrumented_groq_client_with_sdk_retries
```

**Step 3 — the code.**

```diff
diff --git a/backend/llm/anthropic_client.py b/backend/llm/anthropic_client.py
index 9777249..e2bfbcc 100644
--- a/backend/llm/anthropic_client.py
+++ b/backend/llm/anthropic_client.py
@@ -1,16 +1,22 @@
 import json
 import os
 import anthropic
+from config import llm_timeout_seconds
 from .base import BaseLLMClient, LLMMessage, LLMResponse, ToolDefinition
 
 
 class AnthropicClient(BaseLLMClient):
 
-    def __init__(self) -> None:
+    def __init__(self, max_retries: int | None = None) -> None:
         api_key = os.environ.get("ANTHROPIC_API_KEY")
         if not api_key:
             raise RuntimeError("ANTHROPIC_API_KEY is not set")
-        self._client = anthropic.Anthropic(api_key=api_key)
+        # max_retries=None keeps the SDK's own retries (single-provider mode). A fallback chain
+        # passes 0: there the next provider is the retry.
+        options: dict = {"api_key": api_key, "timeout": llm_timeout_seconds()}
+        if max_retries is not None:
+            options["max_retries"] = max_retries
+        self._client = anthropic.Anthropic(**options)
         self._model = os.environ.get("ANTHROPIC_MODEL", "claude-haiku-4-5")
 
     @property
diff --git a/backend/llm/groq_client.py b/backend/llm/groq_client.py
index aa4094d..eee4330 100644
--- a/backend/llm/groq_client.py
+++ b/backend/llm/groq_client.py
@@ -1,15 +1,21 @@
 import os
 from groq import BadRequestError, Groq
+from config import llm_timeout_seconds
 from .base import BaseLLMClient, LLMMessage, LLMResponse, ToolDefinition
 
 
 class GroqClient(BaseLLMClient):
 
-    def __init__(self) -> None:
+    def __init__(self, max_retries: int | None = None) -> None:
         api_key = os.environ.get("GROQ_API_KEY")
         if not api_key:
             raise RuntimeError("GROQ_API_KEY is not set")
-        self._client = Groq(api_key=api_key)
+        # max_retries=None keeps the SDK's own retries (single-provider mode). A fallback chain
+        # passes 0: there the next provider is the retry.
+        options: dict = {"api_key": api_key, "timeout": llm_timeout_seconds()}
+        if max_retries is not None:
+            options["max_retries"] = max_retries
+        self._client = Groq(**options)
         # llama-3.3-70b-versatile was shut down by Groq 2026-08-16; openai/gpt-oss-120b
         # is Groq's official migration target and supports tool calling.
         self._model = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")
diff --git a/backend/services/llm_agent.py b/backend/services/llm_agent.py
index dff8646..6bb036c 100644
--- a/backend/services/llm_agent.py
+++ b/backend/services/llm_agent.py
@@ -1,6 +1,7 @@
 import json
 import os
 import logging
+from config import llm_provider_chain
 from graph.base import GraphContextProvider
 from graph.factory import get_graph_provider
 from llm.base import BaseLLMClient, LLMMessage
@@ -12,17 +13,54 @@ from services.triage_eval import check_emergency_mismatch, check_facility_ground
 logger = logging.getLogger(__name__)
 
 
-def get_llm_client() -> BaseLLMClient:
-    """
-    Factory. Reads LLM_PROVIDER env var.
-    Import is deferred so unused provider packages don't cause ImportError.
-    """
-    provider = os.environ.get("LLM_PROVIDER", "groq").lower()
+KNOWN_PROVIDERS = ("groq", "openai", "anthropic")
+
+
+def _build_provider_client(provider: str, max_retries: int | None) -> BaseLLMClient:
+    """One provider client. Imports are deferred so unused provider packages don't cause ImportError."""
     if provider == "anthropic":
         from llm.anthropic_client import AnthropicClient
-        return AnthropicClient()
+        return AnthropicClient(max_retries=max_retries)
+    if provider == "openai":
+        from llm.openai_client import OpenAIClient
+        return OpenAIClient(max_retries=max_retries)
     from llm.groq_client import GroqClient
-    return GroqClient()
+    return GroqClient(max_retries=max_retries)
+
+
+def get_llm_client() -> BaseLLMClient:
+    """
+    Factory. Every provider client comes back wrapped in InstrumentedLLMClient.
+
+    LLM_PROVIDER_CHAIN unset: one client chosen by LLM_PROVIDER (groq by default), with the SDK's
+    own retries, exactly as before.
+    LLM_PROVIDER_CHAIN="groq,openai,anthropic": those providers in that order behind
+    FallbackLLMClient, each with SDK retries off (the next provider is the retry). A name that is
+    unknown, or whose key is missing, is skipped with a warning.
+    """
+    from llm.instrumented import InstrumentedLLMClient
+
+    chain = llm_provider_chain()
+    if not chain:
+        provider = os.environ.get("LLM_PROVIDER", "groq").lower()
+        if provider not in KNOWN_PROVIDERS:
+            provider = "groq"
+        return InstrumentedLLMClient(_build_provider_client(provider, None), provider)
+
+    from llm.fallback import FallbackLLMClient
+
+    clients: list[BaseLLMClient] = []
+    for provider in chain:
+        if provider not in KNOWN_PROVIDERS:
+            logger.warning("llm_provider_skipped", extra={"provider": provider, "reason": "unknown provider"})
+            continue
+        try:
+            clients.append(InstrumentedLLMClient(_build_provider_client(provider, 0), provider))
+        except RuntimeError as exc:  # a missing key or model
+            logger.warning("llm_provider_skipped", extra={"provider": provider, "reason": str(exc)})
+    if not clients:
+        raise RuntimeError("LLM_PROVIDER_CHAIN names no usable provider")
+    return FallbackLLMClient(clients)
 
 
 class LLMAgent:
```

**Step 4 — the tests pass.** `pytest tests/llm/test_client_factory.py -q` ends with `10 passed in 0.25s`.


---

# Part 3 — Load scripts, documentation, chat fix

### Task 10: k6 load-test scripts

**Commit:** `test: add k6 load test scripts for the non-llm mix and the chat path`

**Files:**
- Create: `backend/scripts/load/README.md`
- Create: `backend/scripts/load/lib.js`
- Create: `backend/scripts/load/scenarios.json`
- Create: `backend/scripts/load/test_a.js`
- Create: `backend/scripts/load/test_b.js`

**Interfaces:** Produces: `backend/scripts/load/` (`lib.js`, `test_a.js`, `test_b.js`, `scenarios.json`, `README.md`). No application code changes.

**Change.**

````diff
diff --git a/backend/scripts/load/README.md b/backend/scripts/load/README.md
new file mode 100644
index 0000000..2f620b5
--- /dev/null
+++ b/backend/scripts/load/README.md
@@ -0,0 +1,33 @@
+# Load tests (k6)
+
+Run through the official k6 image; nothing is installed on the host. Run from the repository
+root. Results go to `artifacts/perf/` (git-ignored).
+
+```bash
+mkdir -p artifacts/perf
+
+# Test A, non-LLM. SCENARIO: smoke | average | breakpoint | soak
+docker run --rm -i --network host --user "$(id -u):$(id -g)" \
+  -e BASE_URL=https://<api-under-test> -e INTERNAL_TOKEN="$DEMO_INTERNAL_TOKEN" -e SCENARIO=smoke \
+  -v "$PWD/backend/scripts/load:/scripts:ro" -v "$PWD/artifacts/perf:/out" \
+  grafana/k6 run /scripts/test_a.js --summary-export /out/test-a-smoke.json
+
+# Test B, chat. Spends LLM quota on every turn.
+docker run --rm -i --network host --user "$(id -u):$(id -g)" \
+  -e BASE_URL=https://<api-under-test> -e INTERNAL_TOKEN="$DEMO_INTERNAL_TOKEN" -e STEPS=1,2,5,10,20,40 \
+  -v "$PWD/backend/scripts/load:/scripts:ro" -v "$PWD/artifacts/perf:/out" \
+  grafana/k6 run /scripts/test_b.js --summary-export /out/test-b.json
+```
+
+Before a run against a deployed API:
+
+- Never point these at the public demo service. The target is the staging service.
+- Raise `RATE_LIMIT_CHAT_IP` and `RATE_LIMIT_ROUTES_IP` on the target: every request comes from
+  one IP, and with the defaults the test measures the limiter after 30 chat turns.
+- Set `DEMO_INTERNAL_TOKEN` on the target and pass the same value as `INTERNAL_TOKEN`, so the
+  guests the test creates are marked internal and can be deleted afterwards.
+- Set `ROUTING_SHADOW_SAMPLE_RATE=0` on the target for Test B: the shadow comparison makes an
+  extra Geoapify call on a share of chat turns.
+
+`POST /routes` is capped at 2 requests per second in every Test A scenario because each request
+makes three calls on the metered Geoapify key. Transit is not exercised under load.
diff --git a/backend/scripts/load/lib.js b/backend/scripts/load/lib.js
new file mode 100644
index 0000000..d39a1e6
--- /dev/null
+++ b/backend/scripts/load/lib.js
@@ -0,0 +1,40 @@
+// Shared helpers for the k6 load tests. Run through the official image; see README.md here.
+//
+//   BASE_URL        API under test, no trailing slash (required)
+//   INTERNAL_TOKEN  value of DEMO_INTERNAL_TOKEN on that API, so test guests are marked internal
+
+export const BASE_URL = (__ENV.BASE_URL || '').replace(/\/+$/, '');
+if (!BASE_URL) {
+  throw new Error('BASE_URL is not set');
+}
+
+const INTERNAL_TOKEN = __ENV.INTERNAL_TOKEN || '';
+
+// k6 has no crypto.randomUUID; the API only needs a well-formed v4 UUID as a guest id.
+export function uuid4() {
+  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
+    const r = Math.floor(Math.random() * 16);
+    return (c === 'x' ? r : (r % 4) + 8).toString(16);
+  });
+}
+
+export function guestHeaders(guestId) {
+  const headers = { 'Content-Type': 'application/json', 'X-Guest-Id': guestId };
+  if (INTERNAL_TOKEN) {
+    headers['X-Internal'] = INTERNAL_TOKEN;
+  }
+  return headers;
+}
+
+// A point on land inside the area the facility data covers. The band starts north of the
+// shoreline on purpose: a point in Lake Ontario makes the routing provider answer 400.
+export function randomTorontoPoint() {
+  return {
+    lat: 43.69 + Math.random() * 0.09,
+    lng: -79.52 + Math.random() * 0.26,
+  };
+}
+
+export function pick(items) {
+  return items[Math.floor(Math.random() * items.length)];
+}
diff --git a/backend/scripts/load/scenarios.json b/backend/scripts/load/scenarios.json
new file mode 100644
index 0000000..a392082
--- /dev/null
+++ b/backend/scripts/load/scenarios.json
@@ -0,0 +1,62 @@
+[
+  {
+    "message": "I have crushing chest pain radiating to my left arm and I can't catch my breath.",
+    "lat": 43.6426,
+    "lng": -79.3871
+  },
+  {
+    "message": "My face is drooping on one side and I can't lift my right arm, this started 10 minutes ago.",
+    "lat": 43.6511,
+    "lng": -79.347
+  },
+  {
+    "message": "I'm having a severe allergic reaction, my throat is closing up and my face is swelling.",
+    "lat": 43.6629,
+    "lng": -79.3957
+  },
+  {
+    "message": "I was in a car accident and there's heavy bleeding from a deep cut on my leg that won't stop.",
+    "lat": 43.6205,
+    "lng": -79.5132
+  },
+  {
+    "message": "My child is unconscious and not responding after falling down the stairs.",
+    "lat": 43.7,
+    "lng": -79.4163
+  },
+  {
+    "message": "I suddenly can't see out of one eye and have the worst headache of my life.",
+    "lat": 43.689,
+    "lng": -79.4507
+  },
+  {
+    "message": "I'm having a seizure right now, this is the third one in an hour.",
+    "lat": 43.7615,
+    "lng": -79.4111
+  },
+  {
+    "message": "I'm coughing up blood and have severe difficulty breathing that's getting worse.",
+    "lat": 43.6435,
+    "lng": -79.5656
+  },
+  {
+    "message": "My baby has a fever of 40C and is limp and won't wake up.",
+    "lat": 43.7532,
+    "lng": -79.3832
+  },
+  {
+    "message": "I took too much of my medication by accident and I'm feeling dizzy and confused.",
+    "lat": 43.6677,
+    "lng": -79.42
+  },
+  {
+    "message": "I have sudden severe abdominal pain and I've been vomiting blood.",
+    "lat": 43.7042,
+    "lng": -79.355
+  },
+  {
+    "message": "I burned myself badly with boiling water and the skin is blistering over a large area.",
+    "lat": 43.6108,
+    "lng": -79.4849
+  }
+]
diff --git a/backend/scripts/load/test_a.js b/backend/scripts/load/test_a.js
new file mode 100644
index 0000000..429a392
--- /dev/null
+++ b/backend/scripts/load/test_a.js
@@ -0,0 +1,118 @@
+// Test A: non-LLM capacity. No chat traffic, so it spends no LLM quota.
+//
+//   SCENARIO   smoke | average | breakpoint | soak   (default smoke)
+//   AVG_RATE   requests per second for average and soak (default 10)
+//
+// Two streams run side by side:
+//   mix     GET /facilities, /facilities/nearby, /config, /health, by weight
+//   routes  POST /routes at a low fixed rate. Each call makes three calls on the metered Geoapify
+//           key, so it is capped at 2 per second in every scenario and never ramps.
+import http from 'k6/http';
+import { check } from 'k6';
+import { BASE_URL, guestHeaders, pick, randomTorontoPoint, uuid4 } from './lib.js';
+
+const SCENARIO = __ENV.SCENARIO || 'smoke';
+const AVG_RATE = Number(__ENV.AVG_RATE || 10);
+
+const ROUTES_PER_SECOND = { smoke: 0.2, average: 1, breakpoint: 2, soak: 0.5 };
+
+// Arrival rate, not looping users: a slow server must not slow the generator down and hide the tail.
+const MIX = {
+  smoke: { executor: 'constant-arrival-rate', rate: 2, timeUnit: '1s', duration: '1m', preAllocatedVUs: 5, maxVUs: 20 },
+  average: {
+    executor: 'ramping-arrival-rate', startRate: 1, timeUnit: '1s', preAllocatedVUs: 50, maxVUs: 200,
+    stages: [
+      { target: AVG_RATE, duration: '1m' },
+      { target: AVG_RATE, duration: '5m' },
+      { target: 0, duration: '30s' },
+    ],
+  },
+  breakpoint: {
+    executor: 'ramping-arrival-rate', startRate: 10, timeUnit: '1s', preAllocatedVUs: 200, maxVUs: 1000,
+    stages: [10, 25, 50, 100, 150, 200].flatMap((rate) => [
+      { target: rate, duration: '15s' },
+      { target: rate, duration: '2m' },
+    ]),
+  },
+  soak: { executor: 'constant-arrival-rate', rate: AVG_RATE, timeUnit: '1s', duration: '1h', preAllocatedVUs: 50, maxVUs: 200 },
+};
+
+if (!MIX[SCENARIO]) {
+  throw new Error(`unknown SCENARIO "${SCENARIO}"`);
+}
+
+const routesRate = ROUTES_PER_SECOND[SCENARIO];
+
+export const options = {
+  scenarios: {
+    mix: { ...MIX[SCENARIO], exec: 'mix' },
+    routes: {
+      executor: 'constant-arrival-rate',
+      // k6 wants whole numbers: 0.2 per second is 1 every 5 seconds.
+      rate: routesRate >= 1 ? routesRate : 1,
+      timeUnit: routesRate >= 1 ? '1s' : `${Math.round(1 / routesRate)}s`,
+      duration: SCENARIO === 'smoke' ? '1m' : SCENARIO === 'soak' ? '1h' : SCENARIO === 'average' ? '6m30s' : '13m30s',
+      preAllocatedVUs: 10,
+      maxVUs: 40,
+      exec: 'routes',
+    },
+  },
+  // Our own targets, stated as assumptions in the spec; not an industry standard.
+  thresholds: {
+    'http_req_failed{scenario:mix}': [{ threshold: 'rate<0.01', abortOnFail: SCENARIO === 'breakpoint', delayAbortEval: '2m' }],
+    'http_req_duration{scenario:mix}': [
+      { threshold: 'p(95)<500', abortOnFail: SCENARIO === 'breakpoint', delayAbortEval: '2m' },
+      'p(99)<1000',
+    ],
+    'http_req_failed{scenario:routes}': ['rate<0.05'],
+    'http_req_duration{scenario:routes}': ['p(95)<5000'],
+  },
+  summaryTrendStats: ['avg', 'min', 'med', 'p(90)', 'p(95)', 'p(99)', 'max'],
+};
+
+const CATEGORIES = [null, 'hospital', 'ambulatory', 'residential'];
+const RADII = [5000, 10000, 25000, 50000];
+const MODES = ['car', 'bike', 'walk']; // no transit: slowest and the costliest on the provider
+
+export function setup() {
+  const res = http.get(`${BASE_URL}/facilities?category=hospital`, { tags: { name: 'setup' } });
+  if (res.status !== 200) {
+    throw new Error(`setup: GET /facilities answered ${res.status}`);
+  }
+  const hospitalIds = res.json().map((f) => f.id);
+  if (hospitalIds.length < 3) {
+    throw new Error('setup: fewer than 3 hospitals returned');
+  }
+  return { hospitalIds };
+}
+
+export function mix() {
+  const roll = Math.random() * 100;
+  let res;
+  if (roll < 42) {
+    res = http.get(`${BASE_URL}/facilities`, { tags: { name: 'facilities' } });
+  } else if (roll < 74) {
+    const point = randomTorontoPoint();
+    const category = pick(CATEGORIES);
+    const query = `lat=${point.lat}&lng=${point.lng}&radius_m=${pick(RADII)}` + (category ? `&category=${category}` : '');
+    res = http.get(`${BASE_URL}/facilities/nearby?${query}`, { tags: { name: 'nearby' } });
+  } else if (roll < 90) {
+    res = http.get(`${BASE_URL}/config`, { tags: { name: 'config' } });
+  } else {
+    res = http.get(`${BASE_URL}/health`, { tags: { name: 'health' } });
+  }
+  check(res, { 'status is 200': (r) => r.status === 200 });
+}
+
+export function routes(data) {
+  const ids = [];
+  while (ids.length < 3) {
+    const id = pick(data.hospitalIds);
+    if (!ids.includes(id)) {
+      ids.push(id);
+    }
+  }
+  const body = JSON.stringify({ origin: randomTorontoPoint(), facility_ids: ids, mode: pick(MODES) });
+  const res = http.post(`${BASE_URL}/routes`, body, { headers: guestHeaders(uuid4()), tags: { name: 'routes' } });
+  check(res, { 'routes answered 200': (r) => r.status === 200 });
+}
diff --git a/backend/scripts/load/test_b.js b/backend/scripts/load/test_b.js
new file mode 100644
index 0000000..296a46f
--- /dev/null
+++ b/backend/scripts/load/test_b.js
@@ -0,0 +1,78 @@
+// Test B: the chat path, measured on its own. Every turn spends real LLM quota.
+//
+//   STEPS       comma-separated concurrent-turn levels (default 1,2,5,10,20,40)
+//   STEP_HOLD   how long each level is held (default 2m)
+//
+// One iteration is one fresh guest: create a session, send one symptom message, read the reply.
+// A fresh guest per turn keeps the per-guest rate limit out of the way; the per-IP limit must be
+// raised on the API under test (RATE_LIMIT_CHAT_IP), or the test measures the limiter.
+import http from 'k6/http';
+import { check, sleep } from 'k6';
+import { Counter, Rate, Trend } from 'k6/metrics';
+import { SharedArray } from 'k6/data';
+import { BASE_URL, guestHeaders, pick, uuid4 } from './lib.js';
+
+const STEPS = (__ENV.STEPS || '1,2,5,10,20,40').split(',').map((s) => Number(s.trim()));
+const STEP_HOLD = __ENV.STEP_HOLD || '2m';
+
+const scenarios = new SharedArray('symptom scenarios', () => JSON.parse(open('./scenarios.json')));
+
+const turnDuration = new Trend('chat_turn_duration', true);
+const turnBusy = new Rate('chat_turn_busy');           // 429 from our limiter or the provider's quota
+const turnFailed = new Rate('chat_turn_failed');       // anything else that is not a 200
+const turnsWithRecommendation = new Counter('chat_turns_with_recommendation');
+
+export const options = {
+  scenarios: {
+    chat: {
+      executor: 'ramping-vus',
+      startVUs: 0,
+      gracefulRampDown: '30s',
+      stages: STEPS.flatMap((level) => [
+        { target: level, duration: '10s' },
+        { target: level, duration: STEP_HOLD },
+      ]),
+    },
+  },
+  // Our own targets, stated as assumptions in the spec. Once chat_turn_busy rises, the test is
+  // measuring a rate limit (ours or the provider's), not this API.
+  thresholds: {
+    chat_turn_duration: [{ threshold: 'p(95)<15000', abortOnFail: true, delayAbortEval: STEP_HOLD }],
+    chat_turn_failed: [{ threshold: 'rate<0.05', abortOnFail: true, delayAbortEval: STEP_HOLD }],
+    chat_turn_busy: ['rate<0.05'],
+  },
+  summaryTrendStats: ['avg', 'min', 'med', 'p(90)', 'p(95)', 'p(99)', 'max'],
+};
+
+export default function () {
+  const scenario = pick(scenarios);
+  const headers = guestHeaders(uuid4());
+
+  const session = http.post(
+    `${BASE_URL}/chat/sessions`,
+    JSON.stringify({ first_message: scenario.message }),
+    { headers, tags: { name: 'chat_session' } },
+  );
+  if (!check(session, { 'session created': (r) => r.status === 200 })) {
+    turnFailed.add(true);
+    sleep(1);
+    return;
+  }
+
+  const turn = http.post(
+    `${BASE_URL}/chat/message`,
+    JSON.stringify({ session_id: session.json('id'), content: scenario.message, lat: scenario.lat, lng: scenario.lng }),
+    { headers, tags: { name: 'chat_message' }, timeout: '90s' },
+  );
+
+  turnBusy.add(turn.status === 429);
+  turnFailed.add(turn.status !== 200 && turn.status !== 429);
+  if (turn.status === 200) {
+    turnDuration.add(turn.timings.duration);
+    const triage = turn.json('triage');
+    if (triage && triage.recommended_facility) {
+      turnsWithRecommendation.add(1);
+    }
+  }
+  sleep(1);
+}
````

**Check.** Both scripts parse for every scenario with `k6 inspect` in the official k6 image (`docker run --rm -v "$PWD/backend/scripts/load:/scripts:ro" grafana/k6 inspect -e BASE_URL=... -e SCENARIO=... /scripts/test_a.js`), and the smoke scenario of Test A and a short Test B were run against a local server.

### Task 11: Documentation

**Commit:** `docs: document metrics, settings and provider fallback and record sprint 21 phase 2 code`

**Files:**
- Modify: `CHANGELOG.md`
- Modify: `docs/API.md`

**Interfaces:** Produces: an operations section in `docs/API.md`; Phase 2 code items ticked in `CHANGELOG.md`.

**Change.**

```diff
diff --git a/CHANGELOG.md b/CHANGELOG.md
index 0ffd87a..d7a6834 100644
--- a/CHANGELOG.md
+++ b/CHANGELOG.md
@@ -841,9 +841,9 @@ branch is deployed. Spec and plan: `docs/superpowers/specs/2026-10-08-guest-demo
 
 **Phase 2 — performance tracking and measurement**
 
-- [ ] Latency histograms with one shape for the LLM call, routing and the graph call (the last records nothing until the instance is back); LLM outcome counter (errors, 429s); pool stats exported
-- [ ] Demo pool size from an environment variable (hardcoded to 5 today), default set from the load test
-- [ ] Rate-limit values from environment variables, defaults unchanged, raised on staging only
+- [x] Latency histograms with one shape for the LLM call, routing and the graph call (the last records nothing until the instance is back); LLM outcome counter (errors, 429s); pool stats exported
+- [x] Demo pool size from an environment variable (hardcoded to 5 today), default set from the load test
+- [x] Rate-limit values from environment variables, defaults unchanged, raised on staging only
 - [ ] `pg_stat_statements` enabled on the demo database (admin step, needs a restart)
 - [ ] `/metrics` read directly during tests (Grafana Cloud holds no data yet, see the last item) during tests
 - [ ] Test A, non-LLM: smoke, average load, breakpoint, one-hour soak
@@ -852,7 +852,17 @@ branch is deployed. Spec and plan: `docs/superpowers/specs/2026-10-08-guest-demo
 - [ ] Web Vitals at the 75th percentile compared with the published "good" thresholds
 - [ ] Report: environment, mix, one row per load step, breakpoint and first bottleneck
 - [ ] Latency fix, only if the report or the journey timings show one dominant cost
-- [ ] Fix the metrics push to Grafana Cloud. Found 2026-10-10: the Prometheus store there has never received an API metric (only Grafana's own three alert series in 90 days; "Service down" is firing, the two others are in no-data). The push thread in `backend/observability.py` fails every 30 seconds with `'Response' object is not callable`, and it uses the Pushgateway method against a remote-write URL, which are different protocols. Until it is fixed, `/metrics` read directly (it resets on every deploy) is the only source
+- [ ] Fix the metrics push to Grafana Cloud (code done: the push thread is removed and `/metrics` is closed without a token; the Grafana Cloud scrape job is still to create). Found 2026-10-10: the Prometheus store there has never received an API metric (only Grafana's own three alert series in 90 days; "Service down" is firing, the two others are in no-data). The push thread in `backend/observability.py` fails every 30 seconds with `'Response' object is not callable`, and it uses the Pushgateway method against a remote-write URL, which are different protocols. Until it is fixed, `/metrics` read directly (it resets on every deploy) is the only source
+
+Phase 2 code as built (2026-10-10): application metrics on `/metrics` (LLM, routing and graph
+timings, LLM outcomes and tokens, database pool gauges); pool size, pool wait, rate limits and the
+LLM timeout from environment variables; an OpenAI provider and an ordered provider fallback behind
+`LLM_PROVIDER_CHAIN`, off by default and not to be enabled for guests before the triage vignette
+check; k6 scripts for the non-LLM mix and the chat path under `backend/scripts/load/`; chat turns
+moved off the event loop (one turn used to stall every other request of the single worker). The
+measurement runbook (load tests, profiling, report, Grafana scrape job) is still to run. Spec and
+plan: `docs/superpowers/specs/2026-10-10-guest-demo-sprint2-phase2-design.md`,
+`docs/superpowers/plans/2026-10-10-guest-demo-sprint2-phase2.md`.
 
 **Exit:** deployed to `preview`, smoke test passing.
 
diff --git a/docs/API.md b/docs/API.md
index 1b2415c..449c348 100644
--- a/docs/API.md
+++ b/docs/API.md
@@ -166,6 +166,56 @@ Query: `lat`, `lng`, `radius_m` (default 5000, capped at 50000), optional `categ
 on the in-memory facility list with a straight-line distance; the three `eta_*_min` fields are
 fixed-speed estimates kept for the response shape and are not travel times from a routing engine.
 
+## Operations: metrics and settings
+
+### GET `/metrics`
+
+Prometheus text format. **Auth:** `Authorization: Bearer <METRICS_BEARER_TOKEN>`. Answers 503
+when the token is not configured and 403 on a wrong one. Grafana Cloud scrapes this endpoint
+(Metrics Endpoint integration); the API pushes nothing.
+
+Counters and histograms live in the process and restart with it. The API runs as one worker;
+with several workers each would report its own numbers.
+
+| Metric | Type | Labels |
+|---|---|---|
+| `http_requests_total`, `http_request_duration_seconds` | per route | `handler`, `method`, `status` |
+| `llm_call_duration_seconds` | histogram | `provider`, `outcome` |
+| `llm_calls_total` | counter | `provider`, `outcome` (`ok`, `rate_limited`, `timeout`, `error`) |
+| `llm_tokens_total` | counter | `provider`, `kind` (`prompt`, `completion`) |
+| `routing_call_duration_seconds` | histogram | `mode`, `outcome` (`ok`, `no_route`, `timeout`, `error`) |
+| `graph_lookup_duration_seconds` | histogram | `provider` (value of `GRAPH_RAG_PROVIDER`), `outcome` |
+| `demo_db_pool_size`, `demo_db_pool_in_use`, `demo_db_pool_waiting` | gauge | none |
+
+### Settings
+
+Read at call time. A missing, malformed or out-of-range number falls back to the default with
+one `env_setting_invalid` warning.
+
+| Variable | Default | Meaning |
+|---|---|---|
+| `DEMO_DB_POOL_MAX` | 5 (1 to 50) | Largest number of demo database connections |
+| `DEMO_DB_POOL_TIMEOUT_SECONDS` | 5 (1 to 60) | How long a request waits for a free connection |
+| `RATE_LIMIT_CHAT_GUEST`, `RATE_LIMIT_CHAT_IP` | 10, 30 | Chat messages per guest and per IP per 10 minutes |
+| `RATE_LIMIT_ROUTES_GUEST`, `RATE_LIMIT_ROUTES_IP` | 60, 180 | Route requests per guest and per IP per 10 minutes |
+| `LLM_TIMEOUT_SECONDS` | 30 (1 to 300) | Timeout of one provider call |
+| `LLM_PROVIDER` | `groq` | Single provider: `groq`, `openai` or `anthropic` |
+| `LLM_PROVIDER_CHAIN` | unset | Ordered fallback, for example `groq,openai,anthropic`. Wins over `LLM_PROVIDER` |
+| `OPENAI_API_KEY`, `OPENAI_MODEL` | none | Required for the `openai` provider. The model has no default |
+
+The rate-limit variables exist for load tests on staging; the public demo keeps the defaults.
+
+### LLM provider fallback
+
+With `LLM_PROVIDER_CHAIN` set, a chat call goes to the first provider and moves to the next one
+when the failure belongs to that provider: rate limit (429), timeout, server error (5xx),
+connection failure, or rejected credentials (401, 403). Any other error is raised at once. Each
+provider is tried once per call, with its SDK retries off. A switch logs `llm_fallback` with
+`from_provider`, `to_provider` and `outcome`, and both attempts appear in `llm_calls_total`.
+
+Do not enable a chain for guests before the triage vignette check has run on every model in it:
+a different model can classify severity differently.
+
 ## Shared Types Reference
 
 Canonical definitions live in `shared/types.ts`. Replicated here for documentation.
```

### Task 12: Chat turns off the event loop

**Commit:** `fix: run chat turns off the event loop`

**Files:**
- Modify: `backend/routers/chat.py`
- Modify: `backend/tests/test_chat.py`

**Interfaces:** Consumes: nothing new. Produces: `send_message` and `create_new_session` run `add_message`, `agent.respond` and `create_session` through `run_in_threadpool`. Responses and error handling are unchanged. **This task must stay the last commit**: the measurement runbook deploys the commit before it first.

**Step 1 — tests first.**

```diff
diff --git a/backend/tests/test_chat.py b/backend/tests/test_chat.py
index 8d65550..3754771 100644
--- a/backend/tests/test_chat.py
+++ b/backend/tests/test_chat.py
@@ -564,3 +564,68 @@ class TestGuestChat:
                 "/chat/message", json={"session_id": FAKE_SESSION_ID, "content": "hi"})
         assert resp.status_code == 200
         limit.assert_not_called()
+
+
+# ── Blocking work stays off the event loop ────────────────────────────────────
+
+def _on_event_loop() -> bool:
+    """True when called on the thread that runs the event loop (a worker thread has none)."""
+    import asyncio
+
+    try:
+        asyncio.get_running_loop()
+    except RuntimeError:
+        return False
+    return True
+
+
+class TestChatDoesNotBlockTheEventLoop:
+    """The agent makes two LLM round trips and the store calls hit the database. Run on the event
+    loop they stall every other request of the single worker; they must run in the thread pool."""
+
+    def test_agent_and_message_writes_run_in_the_thread_pool(self):
+        seen: dict[str, bool] = {}
+
+        def respond(**_: object) -> dict:
+            seen["respond"] = _on_event_loop()
+            return _TRIAGE_RESULT
+
+        def add_message(**kwargs: object) -> dict:
+            seen[f"add_{kwargs['role']}"] = _on_event_loop()
+            return _msg(str(kwargs["role"]))
+
+        agent = MagicMock()
+        agent.respond.side_effect = respond
+        with patch("routers.chat.check_rate_limit", return_value=None), \
+             patch("routers.chat.add_message", side_effect=add_message), \
+             patch("services.llm_agent.LLMAgent", return_value=agent), \
+             patch("routers.chat.guest_store.record_event"), \
+             patch("routers.chat.should_sample", return_value=False):
+            resp = _guest_client().post("/chat/message", json={"session_id": FAKE_SESSION_ID, "content": "hi"})
+
+        assert resp.status_code == 200
+        assert seen == {"add_user": False, "respond": False, "add_assistant": False}
+
+    def test_session_creation_runs_in_the_thread_pool(self):
+        seen: dict[str, bool] = {}
+        session = {"id": FAKE_SESSION_ID, "user_id": FAKE_USER_ID_STR, "title": "hi",
+                   "created_at": "2026-10-07T00:00:00Z", "updated_at": "2026-10-07T00:00:00Z"}
+
+        def create_session(**_: object) -> dict:
+            seen["create_session"] = _on_event_loop()
+            return session
+
+        with patch("routers.chat.create_session", side_effect=create_session), \
+             patch("routers.chat.guest_store.record_event"):
+            resp = _guest_client().post("/chat/sessions", json={"first_message": "hi"})
+
+        assert resp.status_code == 200
+        assert seen == {"create_session": False}
+
+    def test_a_foreign_session_is_still_404_through_the_thread_pool(self):
+        from services.guest_store import SessionNotFound
+
+        with patch("routers.chat.check_rate_limit", return_value=None), \
+             patch("routers.chat.add_message", side_effect=SessionNotFound("s")):
+            resp = _guest_client().post("/chat/message", json={"session_id": FAKE_SESSION_ID, "content": "hi"})
+        assert resp.status_code == 404
```

**Step 2 — the tests fail without the code.** `pytest tests/test_chat.py -q` ends with `2 failed, 43 passed in 6.54s`:

```text
E       AssertionError: assert {'add_assista...espond': True} == {'add_assista...spond': False}
E         
E         Differing items:
E         {'add_user': True} != {'add_user': False}
```

**Step 3 — the code.**

```diff
diff --git a/backend/routers/chat.py b/backend/routers/chat.py
index b5835d7..34de3f6 100644
--- a/backend/routers/chat.py
+++ b/backend/routers/chat.py
@@ -98,7 +98,8 @@ async def create_new_session(
     user_id = str(current_user.id)  # type: ignore[attr-defined]
     title = generate_session_title(body.first_message)
 
-    session = create_session(user_id=user_id, title=title)
+    # Blocking database call: keep it off the event loop (see send_message).
+    session = await run_in_threadpool(create_session, user_id=user_id, title=title)
     append_session_to_cache(user_id, session)
     await _record_guest_event(current_user, "session_started", str(session["id"]))
 
@@ -139,8 +140,12 @@ async def send_message(
     if cache_entry:
         history = cache_entry.get("messages", {}).get(session_id, [])
 
+    # The store calls and the agent are blocking (database, two LLM round trips). They run in the
+    # thread pool: on the event loop one chat turn would stall every other request of this worker.
     try:
-        user_msg = add_message(session_id=session_id, user_id=user_id, role="user", content=body.content)
+        user_msg = await run_in_threadpool(
+            add_message, session_id=session_id, user_id=user_id, role="user", content=body.content
+        )
     except guest_store.SessionNotFound:
         raise HTTPException(404, "Session not found") from None
 
@@ -163,7 +168,8 @@ async def send_message(
             except Exception as exc:
                 logger.warning("profile_fetch_failed", extra={"request_id": request_id, "error": str(exc)})
 
-        result = agent.respond(
+        result = await run_in_threadpool(
+            agent.respond,
             user_message=body.content,
             history=history,
             lat=body.lat,
@@ -189,8 +195,8 @@ async def send_message(
             "turn_type": "followup",
         }
 
-    assistant_msg = add_message(
-        session_id=session_id, user_id=user_id, role="assistant", content=result["response"]
+    assistant_msg = await run_in_threadpool(
+        add_message, session_id=session_id, user_id=user_id, role="assistant", content=result["response"]
     )
     append_message_to_cache(user_id, session_id, assistant_msg)
 
```

**Step 4 — the tests pass.** `pytest tests/test_chat.py -q` ends with `45 passed in 4.50s`.


---

## Result

Full backend suite after Task 12: `639 passed, 11 deselected in 7.58s`.

## What follows

The measurement runbook (spec section 10) and the Grafana scrape job. Task 12 is the last commit on purpose, so the commit before it can be deployed
first for the "before" chat measurement.

## Lenses used in this plan

| Skill | Where |
|---|---|
| test-driven-development | Every code task applies its tests first and records the real failing output; the whole sequence was replayed on a clean checkout before it was landed. |
| clean-architecture | `metrics.py` depends on nothing in the application; timing and fallback wrap the provider interface, so the agent does not change (Tasks 1, 6, 8, 9). |
| software-design-philosophy | Few settings, each with a default and a validated reader, so callers decide nothing (Task 1); wrappers add behaviour behind an unchanged interface instead of pass-through layers (Tasks 6, 8). |
| pragmatic-programmer | One error classifier shared by metrics and fallback; one timing helper for three call sites (Tasks 1, 6). |
| refactoring-patterns | The chat fix is a behaviour-preserving change in its own commit, guarded by the existing chat tests plus three new ones (Task 12). |
| release-it | Explicit timeout on every provider call, one retry layer, pool wait exported, `/metrics` fails closed (Tasks 2, 5, 9). |
| system-design, ddia-systems | Capacity is measured before it is changed; timeouts sit above the slowest reply observed (10 s) and below the point where a stuck call would hold a worker thread for minutes (Task 9, spec section 10). |
| supabase-postgres-best-practices | Pool size bounded and observable before it is raised (Task 2). |
