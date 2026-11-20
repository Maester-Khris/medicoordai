import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from scripts.embedding_eval.bench_embedder import capacity_estimate, latency_stats, parse_proc_status  # noqa: E402


def test_latency_stats_percentiles():
    samples = [float(i) for i in range(1, 101)]  # 1..100 ms
    stats = latency_stats(samples)
    assert stats["p50"] == pytest.approx(50.5)
    assert stats["p95"] == pytest.approx(95.05)
    assert stats["p99"] == pytest.approx(99.01)
    assert stats["max"] == 100.0 and stats["n"] == 100
    with pytest.raises(ValueError):
        latency_stats([])


def test_capacity_estimate_matches_the_sprint_22_formula():
    assert capacity_estimate(50.0) == pytest.approx(35.0 * 16.0 / 66.0)  # about 8.5 turns/s
    assert capacity_estimate(0.0) == pytest.approx(35.0)
    assert capacity_estimate(16.0, base_cpu_ms=16.0, base_capacity=35.0) == pytest.approx(17.5)


def test_parse_proc_status_reads_rss_and_threads():
    text = "Name:\tpython\nVmRSS:\t  123456 kB\nThreads:\t7\n"
    assert parse_proc_status(text) == {"rss_mb": pytest.approx(123456 / 1024), "threads": 7}
    assert parse_proc_status("Name:\tx\n") == {"rss_mb": None, "threads": None}
