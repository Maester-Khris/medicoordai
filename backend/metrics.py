"""Application metrics beyond the per-route ones the instrumentator records.

Everything registers on the registry /metrics already serves. This module knows nothing about
the LLM, routing, graph or database code: they import it, it imports none of them.

Label values are small fixed sets (provider, travel mode, outcome). Never put a guest, session,
message or facility value in a label: every distinct value becomes a time series.
"""
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager

from prometheus_client import Counter, Gauge, Histogram

from observability import _registry

# Buckets sit around the values already observed (LLM 1.5 to 10 s, routing 0.5 to 3 s), so
# percentiles interpolate inside populated buckets.
LLM_BUCKETS = (0.25, 0.5, 1, 2, 3, 5, 8, 13, 21, 34)
ROUTING_BUCKETS = (0.1, 0.25, 0.5, 1, 2, 3, 5, 8)
GRAPH_BUCKETS = (0.005, 0.025, 0.1, 0.25, 0.5, 1, 2.5)

LLM_CALL_DURATION = Histogram(
    "llm_call_duration_seconds", "One LLM provider call, end to end",
    ["provider", "outcome"], buckets=LLM_BUCKETS, registry=_registry,
)
LLM_CALLS = Counter(
    "llm_calls_total", "LLM provider calls by outcome (ok, rate_limited, timeout, error)",
    ["provider", "outcome"], registry=_registry,
)
LLM_TOKENS = Counter(
    "llm_tokens_total", "Tokens reported by the provider (kind: prompt, completion)",
    ["provider", "kind"], registry=_registry,
)
ROUTING_CALL_DURATION = Histogram(
    "routing_call_duration_seconds", "One Geoapify Routing call for one candidate facility",
    ["mode", "outcome"], buckets=ROUTING_BUCKETS, registry=_registry,
)
GRAPH_LOOKUP_DURATION = Histogram(
    "graph_lookup_duration_seconds", "One symptom graph context lookup",
    ["provider", "outcome"], buckets=GRAPH_BUCKETS, registry=_registry,
)
POOL_SIZE = Gauge("demo_db_pool_size", "Connections open in the demo database pool", registry=_registry)
POOL_IN_USE = Gauge("demo_db_pool_in_use", "Connections currently checked out", registry=_registry)
POOL_WAITING = Gauge("demo_db_pool_waiting", "Callers waiting for a free connection", registry=_registry)


class Timing:
    """What a `timed` block reports. Set `outcome` inside the block; it defaults to "ok"."""

    def __init__(self) -> None:
        self.outcome = "ok"


@contextmanager
def timed(histogram: Histogram, **labels: str) -> Iterator[Timing]:
    """Observes how long the block took, labelled with `labels` plus the block's outcome.

    An exception leaving the block is recorded as outcome "error" unless the block already set
    something more specific, and is always re-raised unchanged.
    """
    timing = Timing()
    started = time.perf_counter()
    try:
        yield timing
    except BaseException:
        if timing.outcome == "ok":
            timing.outcome = "error"
        raise
    finally:
        histogram.labels(**labels, outcome=timing.outcome).observe(time.perf_counter() - started)


def bind_pool_stats(read_stats: Callable[[], dict[str, int]]) -> None:
    """Makes the three pool gauges read `read_stats()` at scrape time. Called once by demo_db."""
    POOL_SIZE.set_function(lambda: read_stats()["size"])
    POOL_IN_USE.set_function(lambda: read_stats()["in_use"])
    POOL_WAITING.set_function(lambda: read_stats()["waiting"])
