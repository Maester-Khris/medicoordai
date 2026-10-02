"""
Sprint 17 Phase B, case study 2: fires a batch of real triage requests with
varied coordinates against the eval-project preview backend, so the
already-shipped 10%-sampled routing shadow-call (services/geoapify_shadow.py)
accumulates a representative spread of Haversine-vs-real-driving-distance
comparisons — replacing the earlier single-fixed-location smoke sample.

Uses concurrent.futures.ThreadPoolExecutor to fire requests, not a load
testing tool (JMeter/Locust/k6) — this repo's explicit decision for Sprint 17,
consistent with the volume actually needed (request-diversity, not
throughput/stress testing) and with zero new dependencies.

Reuses scripts/triage_deepeval's account pool and scenario list as-is: same
eval Supabase project, same 12 scattered-Toronto-coordinate messages.

Invocation:
    doppler run --config eval -- python scripts/routing_shadow_eval/run_load.py \
        --count 400 --base-url <eval-project preview Railway URL>
"""
import argparse
import concurrent.futures
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from scripts.eval_common.metrics_client import fetch_metrics, parse_metric_value  # noqa: E402
from scripts.triage_deepeval.generate_transcripts import (  # noqa: E402
    create_session,
    load_accounts,
    login,
    send_message,
)
from scripts.triage_deepeval.symptom_scenarios import SYMPTOM_SCENARIOS  # noqa: E402

logger = logging.getLogger(__name__)

RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")
POST_FIRE_SETTLE_SECONDS = 20  # lets in-flight background shadow calls finish before reading "after" metrics


def compute_shadow_stats(before_text: str, after_text: str) -> dict:
    before_count = parse_metric_value(before_text, "routing_shadow_error_km_count")
    after_count = parse_metric_value(after_text, "routing_shadow_error_km_count")
    before_sum = parse_metric_value(before_text, "routing_shadow_error_km_sum")
    after_sum = parse_metric_value(after_text, "routing_shadow_error_km_sum")

    shadow_samples = int(after_count - before_count)
    sum_delta = after_sum - before_sum
    mean_error_km = round(sum_delta / shadow_samples, 4) if shadow_samples > 0 else 0.0

    return {"shadow_samples": shadow_samples, "mean_error_km": mean_error_km}


def _fire_one(token: str, scenario: dict, base_url: str) -> bool:
    try:
        session_id = create_session(base_url, token, scenario["message"])
        send_message(base_url, token, session_id, scenario)
        return True
    except Exception as exc:
        logger.warning("routing_load_request_failed", extra={"error": str(exc)})
        return False


def run(count: int, base_url: str, workers: int) -> dict:
    accounts = load_accounts()
    if not accounts:
        raise RuntimeError("No eval test accounts found — run create_eval_test_accounts.py first.")

    tokens = [login(a["email"], a["password"]) for a in accounts]

    succeeded = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [
            pool.submit(
                _fire_one,
                tokens[i % len(tokens)],
                SYMPTOM_SCENARIOS[i % len(SYMPTOM_SCENARIOS)],
                base_url,
            )
            for i in range(count)
        ]
        for future in concurrent.futures.as_completed(futures):
            if future.result():
                succeeded += 1

    return {"requests_fired": count, "requests_succeeded": succeeded}


def write_results(fire_result: dict, stats: dict, window_start: str, window_end: str) -> str:
    os.makedirs(RESULTS_DIR, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = os.path.join(RESULTS_DIR, f"routing_shadow_results_{stamp}.json")
    payload = {**fire_result, **stats, "window_start": window_start, "window_end": window_end}
    with open(path, "w") as f:
        json.dump(payload, f, indent=2)
    return path


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=400)
    parser.add_argument("--workers", type=int, default=5)
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

    print(f"Settling {POST_FIRE_SETTLE_SECONDS}s for in-flight shadow calls...")
    time.sleep(POST_FIRE_SETTLE_SECONDS)

    after_text = fetch_metrics(args.base_url, args.metrics_token)
    window_end = datetime.now(timezone.utc).isoformat()

    stats = compute_shadow_stats(before_text, after_text)
    path = write_results(fire_result, stats, window_start, window_end)

    print(f"Fired {fire_result['requests_fired']} requests, {fire_result['requests_succeeded']} succeeded")
    print(f"Shadow samples observed: {stats['shadow_samples']}")
    print(f"Mean routing error: {stats['mean_error_km']} km")
    print(f"Full results written to {path}")


if __name__ == "__main__":
    main()
