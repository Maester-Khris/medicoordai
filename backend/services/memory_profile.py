"""Staging-only allocation profile for load tests, behind MEMORY_PROFILE.

`start()` begins tracing and keeps a baseline snapshot; `growth()` compares the live heap to it
and names the allocation sites that grew most. One frame per trace keeps the overhead lowest.
Per process: staging runs one worker, so the report is for the whole API.
"""
import os
import tracemalloc

_baseline: tracemalloc.Snapshot | None = None


def enabled() -> bool:
    return os.environ.get("MEMORY_PROFILE", "").strip().lower() in ("1", "on", "true", "yes")


def start() -> None:
    global _baseline
    if not enabled() or tracemalloc.is_tracing():
        return
    tracemalloc.start(1)
    _baseline = tracemalloc.take_snapshot()


def _rss_bytes() -> int:
    with open("/proc/self/statm") as statm:
        return int(statm.read().split()[1]) * os.sysconf("SC_PAGE_SIZE")


def growth(limit: int = 20) -> dict:
    if _baseline is None:
        start()
    if _baseline is None:
        return {"traced_bytes": 0, "rss_bytes": _rss_bytes(), "top": []}
    stats = tracemalloc.take_snapshot().compare_to(_baseline, "lineno")
    stats.sort(key=lambda s: s.size_diff, reverse=True)
    top = [
        {
            "site": f"{s.traceback[0].filename}:{s.traceback[0].lineno}",
            "size_diff_bytes": s.size_diff,
            "count_diff": s.count_diff,
        }
        for s in stats[:limit]
    ]
    return {"traced_bytes": tracemalloc.get_traced_memory()[0], "rss_bytes": _rss_bytes(), "top": top}
