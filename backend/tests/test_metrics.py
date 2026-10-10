import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from prometheus_client import CollectorRegistry, Histogram

import metrics
from observability import _registry


@pytest.fixture()
def histogram() -> Histogram:
    return Histogram("probe_seconds", "test", ["kind", "outcome"], registry=CollectorRegistry())


def _observations(histogram: Histogram, **labels: str) -> float:
    for family in histogram.collect():
        for sample in family.samples:
            if sample.name.endswith("_count") and sample.labels == labels:
                return sample.value
    return 0.0


def test_timed_records_one_ok_observation(histogram: Histogram) -> None:
    with metrics.timed(histogram, kind="a"):
        pass
    assert _observations(histogram, kind="a", outcome="ok") == 1.0


def test_timed_uses_the_outcome_the_block_sets(histogram: Histogram) -> None:
    with metrics.timed(histogram, kind="a") as timing:
        timing.outcome = "no_route"
    assert _observations(histogram, kind="a", outcome="no_route") == 1.0
    assert _observations(histogram, kind="a", outcome="ok") == 0.0


def test_timed_records_an_escaping_exception_as_error_and_re_raises_it(histogram: Histogram) -> None:
    boom = ValueError("boom")
    with pytest.raises(ValueError) as caught:
        with metrics.timed(histogram, kind="a"):
            raise boom
    assert caught.value is boom
    assert _observations(histogram, kind="a", outcome="error") == 1.0


def test_timed_keeps_a_specific_outcome_when_the_block_raises(histogram: Histogram) -> None:
    with pytest.raises(RuntimeError):
        with metrics.timed(histogram, kind="a") as timing:
            timing.outcome = "rate_limited"
            raise RuntimeError("429")
    assert _observations(histogram, kind="a", outcome="rate_limited") == 1.0
    assert _observations(histogram, kind="a", outcome="error") == 0.0


def test_timed_measures_elapsed_seconds(histogram: Histogram, monkeypatch: pytest.MonkeyPatch) -> None:
    ticks = iter([100.0, 102.5])
    monkeypatch.setattr(metrics.time, "perf_counter", lambda: next(ticks))
    with metrics.timed(histogram, kind="a"):
        pass
    total = [s.value for f in histogram.collect() for s in f.samples
             if s.name.endswith("_sum") and s.labels == {"kind": "a", "outcome": "ok"}]
    assert total == [2.5]


def test_application_metrics_are_on_the_registry_served_by_metrics_endpoint() -> None:
    names = {family.name for family in _registry.collect()}
    assert {
        "llm_call_duration_seconds", "llm_calls", "llm_tokens",
        "routing_call_duration_seconds", "graph_lookup_duration_seconds",
        "demo_db_pool_size", "demo_db_pool_in_use", "demo_db_pool_waiting",
    } <= names


def test_pool_gauges_read_the_bound_function_at_scrape_time() -> None:
    state = {"size": 4, "in_use": 3, "waiting": 2}
    metrics.bind_pool_stats(lambda: state)
    try:
        assert _registry.get_sample_value("demo_db_pool_size") == 4
        assert _registry.get_sample_value("demo_db_pool_in_use") == 3
        state["waiting"] = 7
        assert _registry.get_sample_value("demo_db_pool_waiting") == 7
    finally:
        # Put back the real reader when demo_db provides one, so later tests see live gauges.
        import demo_db
        zeros = {"size": 0, "in_use": 0, "waiting": 0}
        metrics.bind_pool_stats(getattr(demo_db, "pool_stats", lambda: zeros))
