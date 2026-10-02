"""
Sprint 17 Phase B, case study 3: fires a burst of unauthenticated GET
/facilities requests against the eval-project preview backend so the
already-shipped wait_times_cache_outcome_total counter (services/wait_times.py)
accumulates enough reads to report a real cache hit rate — replacing the
earlier 2-call correctness-only smoke check.

Uses concurrent.futures.ThreadPoolExecutor to fire requests, not a load
testing tool — same decision and rationale as routing_shadow_eval/run_load.py.

Invocation:
    doppler run --config eval -- python scripts/cache_load_eval/run_load.py \
        --count 300 --base-url <eval-project preview Railway URL>
"""
import argparse
import concurrent.futures
import json
import logging
import os
import sys
from datetime import datetime, timezone

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from scripts.eval_common.metrics_client import fetch_metrics, parse_metric_value  # noqa: E402

logger = logging.getLogger(__name__)

RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")


def _parse_or_zero(metrics_text: str, name: str, labels: dict[str, str]) -> float:
    # A Prometheus Counter only emits a line for a label combination once it has
    # been incremented at least once in the process — an outcome that has never
    # fired (e.g. no supabase_fallback yet on a freshly deployed, all-cache-hit
    # backend) is legitimately absent from the exposition text, not an error.
    try:
        return parse_metric_value(metrics_text, name, labels)
    except ValueError:
        return 0.0


def compute_hit_rate_stats(before_text: str, after_text: str) -> dict:
    outcomes = ("redis_hit", "supabase_fallback", "total_failure")
    deltas = {}
    for outcome in outcomes:
        before = _parse_or_zero(
            before_text, "wait_times_cache_outcome_total", {"outcome": outcome}
        )
        after = _parse_or_zero(
            after_text, "wait_times_cache_outcome_total", {"outcome": outcome}
        )
        deltas[f"{outcome}_delta"] = int(after - before)

    total = sum(deltas.values())
    hit_rate = round(deltas["redis_hit_delta"] / total, 4) if total > 0 else 0.0

    return {**deltas, "hit_rate": hit_rate}


def _fire_one(base_url: str) -> bool:
    try:
        resp = requests.get(f"{base_url}/facilities", timeout=10)
        resp.raise_for_status()
        return True
    except Exception as exc:
        logger.warning("cache_load_request_failed", extra={"error": str(exc)})
        return False


def run(count: int, base_url: str, workers: int) -> dict:
    succeeded = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_fire_one, base_url) for _ in range(count)]
        for future in concurrent.futures.as_completed(futures):
            if future.result():
                succeeded += 1
    return {"requests_fired": count, "requests_succeeded": succeeded}


def write_results(fire_result: dict, stats: dict, window_start: str, window_end: str) -> str:
    os.makedirs(RESULTS_DIR, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = os.path.join(RESULTS_DIR, f"cache_load_results_{stamp}.json")
    payload = {**fire_result, **stats, "window_start": window_start, "window_end": window_end}
    with open(path, "w") as f:
        json.dump(payload, f, indent=2)
    return path


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=300)
    parser.add_argument("--workers", type=int, default=10)
    parser.add_argument(
        "--base-url",
        default=os.environ.get("EVAL_API_BASE_URL"),
        help="Eval-project preview backend base URL (or set EVAL_API_BASE_URL)",
    )
    parser.add_argument(
        "--metrics-token",
        default=os.environ.get("METRICS_BEARER_TOKEN"),
        help="Bearer token for the protected /metrics endpoint (or set METRICS_BEARER_TOKEN)",
    )
    args = parser.parse_args()

    if not args.base_url:
        raise SystemExit("--base-url or EVAL_API_BASE_URL env var is required")
    if not args.metrics_token:
        raise SystemExit("--metrics-token or METRICS_BEARER_TOKEN env var is required")

    window_start = datetime.now(timezone.utc).isoformat()
    before_text = fetch_metrics(args.base_url, args.metrics_token)

    fire_result = run(args.count, args.base_url, args.workers)

    after_text = fetch_metrics(args.base_url, args.metrics_token)
    window_end = datetime.now(timezone.utc).isoformat()

    stats = compute_hit_rate_stats(before_text, after_text)
    path = write_results(fire_result, stats, window_start, window_end)

    print(f"Fired {fire_result['requests_fired']} requests, {fire_result['requests_succeeded']} succeeded")
    print(f"Redis hit delta: {stats['redis_hit_delta']}, Supabase fallback delta: {stats['supabase_fallback_delta']}")
    print(f"Hit rate: {stats['hit_rate']:.1%}")
    print(f"Full results written to {path}")


if __name__ == "__main__":
    main()
