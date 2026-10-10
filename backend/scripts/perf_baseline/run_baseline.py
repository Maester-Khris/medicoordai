"""Read-only performance snapshot: what the API and the guest journey look like right now.

Reads three things that already exist and writes one dated Markdown report under artifacts/perf/
(git-ignored), so the same read can be repeated after a deploy and compared:

  1. GET /health and /config          what is deployed
  2. GET /metrics                     per-route request counts, mean latency, 5xx share, and overall
                                      p50/p95/p99 from the high-resolution histogram. Counters
                                      restart with the process, so they cover "since the last deploy".
  3. the demo Postgres (optional)     journey timings from message and event timestamps

Nothing is written to the API or the database.

  METRICS_BEARER_TOKEN=... DATABASE_URL=... python run_baseline.py --base-url https://... --label before-phase1
"""
import argparse
import json
import os
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from prometheus_client.parser import text_string_to_metric_families

REPO = Path(__file__).resolve().parents[3]

TURN_SQL = """
    with m as (
        select role, created_at,
               lag(role) over w as prev_role, lag(created_at) over w as prev_at
        from messages window w as (partition by session_id order by created_at)
    )
    select extract(epoch from created_at - prev_at)::float as seconds
    from m where role = 'assistant' and prev_role = 'user'
"""
ROUTE_GAP_SQL = """
    select extract(epoch from d.created_at - r.created_at)::float as seconds
    from events r join events d on d.session_id = r.session_id and d.type = 'route_drawn'
    where r.type = 'recommendation_shown' and d.created_at >= r.created_at
"""
FUNNEL_SQL = """
    select (select count(*) from guests)                                   as guests,
           (select count(*) from guests where is_internal)                 as internal_guests,
           (select count(*) from events where type = 'session_started')    as sessions_started,
           (select count(*) from events where type = 'recommendation_shown') as recommendations_shown,
           (select count(*) from events where type = 'route_drawn')        as routes_drawn,
           (select count(*) from feedback where thumb = 'up')              as thumbs_up,
           (select count(*) from feedback where thumb = 'down')            as thumbs_down
"""
MODE_SQL = "select mode, duration_ms::float / 1000 as seconds from events where type = 'mode_changed'"


def quantile(values: list[float], q: float) -> float | None:
    """Linear-interpolated quantile of raw samples; None for an empty list."""
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def histogram_quantile(buckets: list[tuple[float, float]], q: float) -> float | None:
    """Quantile from cumulative (upper_bound, count) buckets, interpolated inside the bucket."""
    buckets = sorted(buckets)
    if not buckets or buckets[-1][1] == 0:
        return None
    target = q * buckets[-1][1]
    lower_bound, lower_count = 0.0, 0.0
    for upper_bound, count in buckets:
        if count >= target:
            if upper_bound == float("inf"):
                return lower_bound  # beyond the last finite bucket: report its edge
            span = count - lower_count
            return upper_bound if span == 0 else lower_bound + (upper_bound - lower_bound) * (target - lower_count) / span
        lower_bound, lower_count = upper_bound, count
    return None


def get(url: str, token: str | None = None) -> str:
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"} if token else {})
    with urllib.request.urlopen(request, timeout=20) as response:
        return response.read().decode()


def route_stats(metrics_text: str) -> tuple[list[dict], dict[str, float | None]]:
    counts: dict[str, float] = {}
    sums: dict[str, float] = {}
    errors: dict[str, float] = {}
    totals: dict[str, float] = {}
    highr: list[tuple[float, float]] = []
    for family in text_string_to_metric_families(metrics_text):
        for sample in family.samples:
            handler = sample.labels.get("handler", "")
            if sample.name == "http_request_duration_seconds_count":
                counts[handler] = counts.get(handler, 0) + sample.value
            elif sample.name == "http_request_duration_seconds_sum":
                sums[handler] = sums.get(handler, 0) + sample.value
            elif sample.name == "http_requests_total":
                totals[handler] = totals.get(handler, 0) + sample.value
                if sample.labels.get("status", "").startswith("5"):
                    errors[handler] = errors.get(handler, 0) + sample.value
            elif sample.name == "http_request_duration_highr_seconds_bucket":
                highr.append((float(sample.labels["le"]), sample.value))
    rows = [
        {
            "handler": handler,
            "requests": int(count),
            "mean_ms": round(sums.get(handler, 0) / count * 1000) if count else None,
            "error_5xx_pct": round(errors.get(handler, 0) / totals[handler] * 100, 2) if totals.get(handler) else 0.0,
        }
        for handler, count in sorted(counts.items(), key=lambda item: -item[1])
    ]
    overall = {f"p{int(q * 100)}_ms": _ms(histogram_quantile(highr, q)) for q in (0.5, 0.95, 0.99)}
    return rows, overall


def _ms(seconds: float | None) -> float | None:
    return None if seconds is None else round(seconds * 1000)


def summarize(seconds: list[float]) -> dict:
    return {"n": len(seconds), "p50_s": _round(quantile(seconds, 0.5)), "p95_s": _round(quantile(seconds, 0.95)),
            "max_s": _round(max(seconds) if seconds else None)}


def _round(value: float | None) -> float | None:
    return None if value is None else round(value, 2)


def journey(dsn: str) -> dict:
    import psycopg
    from psycopg.rows import dict_row

    with psycopg.connect(dsn.replace("+psycopg", "", 1), connect_timeout=8, row_factory=dict_row) as conn:
        conn.read_only = True
        out: dict = {
            "funnel": conn.execute(FUNNEL_SQL).fetchone(),
            "turn_latency": summarize([r["seconds"] for r in conn.execute(TURN_SQL)]),
            "recommendation_to_route_drawn": summarize([r["seconds"] for r in conn.execute(ROUTE_GAP_SQL)]),
        }
        has_mode = conn.execute(
            "select 1 from information_schema.columns where table_name = 'events' and column_name = 'duration_ms'"
        ).fetchone()
        if has_mode:  # revision 0005 and later
            by_mode: dict[str, list[float]] = {}
            for row in conn.execute(MODE_SQL):
                if row["seconds"] is not None:
                    by_mode.setdefault(row["mode"], []).append(row["seconds"])
            out["mode_change"] = {mode: summarize(values) for mode, values in sorted(by_mode.items())}
    return out


def render(label: str, base_url: str, health: dict, config: dict, rows: list[dict], overall: dict, db: dict | None) -> str:
    lines = [
        f"# Performance snapshot: {label}",
        "",
        f"- Taken: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        f"- API: {base_url}",
        f"- Health: `{json.dumps(health)}`",
        f"- Modes enabled: {config.get('modes_enabled')}",
        "",
        "## API, from /metrics (since the last process start)",
        "",
        (
            f"All routes together: p50 {overall['p50_ms']} ms, p95 {overall['p95_ms']} ms, "
            f"p99 {overall['p99_ms']} ms (interpolated from histogram buckets)."
        ),
        "",
        "| Route | Requests | Mean (ms) | 5xx (%) |",
        "|---|---|---|---|",
    ]
    lines += [f"| `{r['handler']}` | {r['requests']} | {r['mean_ms']} | {r['error_5xx_pct']} |" for r in rows]
    if db is None:
        lines += ["", "## Guest journey", "", "Not read: DATABASE_URL was not set."]
    else:
        lines += ["", "## Guest journey, from the demo database (all rows, internal guests included)", "",
                  f"Funnel: `{json.dumps(db['funnel'])}`", "",
                  "| Measure | n | p50 (s) | p95 (s) | max (s) |", "|---|---|---|---|---|"]
        named = {"User message to assistant reply": db["turn_latency"],
                 "Recommendation shown to route drawn": db["recommendation_to_route_drawn"]}
        named.update({f"Mode change to redraw ({mode})": stats for mode, stats in db.get("mode_change", {}).items()})
        lines += [f"| {name} | {s['n']} | {s['p50_s']} | {s['p95_s']} | {s['max_s']} |" for name, s in named.items()]
        if "mode_change" not in db:
            lines += ["", "Mode-change timings: not available (the events table has no duration column yet)."]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--label", required=True, help="short name used in the report title and file name")
    parser.add_argument("--out-dir", default=str(REPO / "artifacts" / "perf"))
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    token = os.environ.get("METRICS_BEARER_TOKEN")
    health = json.loads(get(f"{base_url}/health"))
    config = json.loads(get(f"{base_url}/config"))
    rows, overall = route_stats(get(f"{base_url}/metrics", token))
    dsn = os.environ.get("DATABASE_URL")
    db = journey(dsn) if dsn else None

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{datetime.now(timezone.utc).strftime('%Y-%m-%d-%H%M')}-{args.label}.md"
    path.write_text(render(args.label, base_url, health, config, rows, overall, db))
    print(f"wrote {path}")


if __name__ == "__main__":
    # smallest check that fails if the percentile maths breaks
    assert quantile([1.0, 2.0, 3.0, 4.0], 0.5) == 2.5 and quantile([], 0.5) is None
    assert histogram_quantile([(0.1, 50), (0.5, 90), (1.0, 100), (float("inf"), 100)], 0.5) == 0.1
    assert round(histogram_quantile([(0.1, 50), (0.5, 90), (1.0, 100), (float("inf"), 100)], 0.95) or 0, 3) == 0.75
    main()
