"""
scraper.py — Railway cron worker (every 15 min). Single entry point.

Run order:
  1. Read the hospital-category facilities from the demo Postgres (medicoord-db-demo)
  2. Scrape ERstat + HowLongWillIWait (ERstat often only has a "Predicted" range, e.g. 45m–2h)
  3. Match scraped names to hospitals: distinctive-word rule + a reviewed alias file
  4. Consolidate: at most one value per source per facility; live values are averaged and always
     beat a predicted range, which is otherwise kept as flagged display text (minutes stay NULL)
  5. Publish to three independent sinks, each as ONE batched write:
       - demo Postgres  `wait_times`  (upsert, one row per facility; live and predicted rows)
       - Supabase       `wait_times`  (insert, live rows only: history table, kept until the Postgres move)
       - Upstash Redis  hash `wait_times:current`  (everything, including "no data" to clear stale values)
  6. Exit non-zero (and report to Sentry) if any sink failed or the match count looks abnormal

Wait times exist only for hospitals. Nothing here creates facilities: new ones are added with the
manual Geoapify enrichment script, never inferred from a scraped name.

Env vars:
    POSTGRES_DB_URL_WORKER      demo Postgres, as the least-privilege worker role
    SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY
    UPSTASH_REDIS_URL           redis://:password@host:port
    SENTRY_DSN_BACKEND          optional (SENTRY_DSN also accepted)

Usage:  python scraper.py [--dry-run]     (--dry-run reads and matches, writes nothing)
"""

import argparse
import json
import logging
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import psycopg
import redis
import requests
import sentry_sdk
from bs4 import BeautifulSoup

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
log = logging.getLogger(__name__)

REDIS_HASH_KEY = "wait_times:current"
ALIASES_PATH = Path(__file__).with_name("hospital_aliases.json")
MIN_JACCARD = 0.6          # share of distinctive words two names must have in common
MIN_MARGIN = 0.2           # best candidate must beat the runner-up by this much
MIN_MATCHED_HOSPITALS = 8  # fewer than this means the sources or the matching broke: write nothing

# Words that do not identify a hospital. Without removing them, "Kingston General Hospital" and
# "Toronto General Hospital" look alike.
STOP_WORDS = frozenset(
    """hospital hospitals health healthcare centre center centres general regional district memorial
    system systems services service network site campus st saint sainte the of and inc sciences science
    care university partners division corporation alliance urgent unit emergency department s""".split()
)

REQUIRED_ENV = ("POSTGRES_DB_URL_WORKER", "SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY", "UPSTASH_REDIS_URL")


# ── names ─────────────────────────────────────────────────────────────────────

def normalize(name: str) -> str:
    n = (name or "").lower().replace("’", "").replace("'", "")
    return " ".join(re.sub(r"[^a-z0-9\s]", " ", n).split())


def distinctive_words(name: str) -> frozenset[str]:
    return frozenset(w for w in normalize(name).split() if w not in STOP_WORDS and len(w) > 1)


# ── time parsing ──────────────────────────────────────────────────────────────

def parse_time_to_minutes(time_str: str) -> int | None:
    """Minutes for a live wait; None for no data and for ERstat's "Predicted" ranges."""
    if not time_str:
        return None
    low = time_str.lower()
    if any(x in low for x in ("no data", "not available", "predicted")) or "—" in time_str:
        return None

    s = low.split("to")[-1] if "to" in low else low
    minutes, has_match = 0, False
    h = re.search(r"(\d+)\s*(?:h|hr|hour)", s)
    m = re.search(r"(\d+)\s*(?:m|min|minute)", s)
    if h:
        minutes += int(h.group(1)) * 60
        has_match = True
    if m:
        minutes += int(m.group(1))
        has_match = True
    elif not h and re.match(r"^\s*(\d+)\s*$", s):
        minutes = int(s.strip())
        has_match = True
    return minutes if has_match else None


def parse_predicted(time_str: str) -> str | None:
    """ERstat's forecast range, as display text: "45m–2hPredicted" -> "45m–2h"; None for anything else."""
    if not time_str or "predicted" not in time_str.lower():
        return None
    text = re.sub("predicted", "", time_str, flags=re.IGNORECASE).strip()
    return text if re.search(r"\d", text) else None


def wait_fields(raw_wait: str) -> dict:
    return {"raw_wait": raw_wait, "wait_minutes": parse_time_to_minutes(raw_wait), "predicted_text": parse_predicted(raw_wait)}


# ── scrapers ──────────────────────────────────────────────────────────────────

_BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"


def parse_erstat(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    rows: list[dict] = []
    hospital_rows = soup.select(".hospital-row")
    if hospital_rows:
        for row in hospital_rows:
            info = row.select_one(".hospital-row-info")
            wait_el = row.select_one(".hospital-row-wait")
            name = info.select_one("h3").get_text(strip=True) if info and info.select_one("h3") else ""
            raw_wait = wait_el.get_text(strip=True) if wait_el else ""
            if name:
                rows.append({"name": name, **wait_fields(raw_wait)})
    else:
        for row in soup.select("table tbody tr"):
            cells = row.find_all(["td", "div"], recursive=False)
            if len(cells) >= 3 and cells[0].get_text(strip=True):
                raw_wait = cells[2].get_text(strip=True)
                rows.append({"name": cells[0].get_text(strip=True), **wait_fields(raw_wait)})
    return rows


def scrape_erstat() -> list[dict]:
    try:
        r = requests.get("https://erstat.ca/hospitals/on", headers={"User-Agent": _BROWSER_UA}, timeout=10)
        r.raise_for_status()
    except requests.RequestException as e:
        log.error("ERstat fetch failed: %s", e)
        return []
    rows = parse_erstat(r.text)
    log.info("ERstat: %d hospitals scraped", len(rows))
    return rows


def scrape_howlongwilliwait() -> list[dict]:
    try:
        r = requests.get("https://howlongwilliwait.com/sample.json",
                         headers={"User-Agent": _BROWSER_UA, "Accept": "application/json"}, timeout=10)
        r.raise_for_status()
        raw = r.json()
    except Exception as e:
        log.error("HowLongWillIWait fetch failed: %s", e)
        return []
    rows = [{"name": name.strip(), **wait_fields(str(w).strip())} for name, w in raw.items() if name and name.strip()]
    log.info("HowLongWillIWait: %d hospitals scraped", len(rows))
    return rows


# ── matching ──────────────────────────────────────────────────────────────────

def load_aliases(path: Path = ALIASES_PATH) -> dict[str, str]:
    """normalized scraped name -> normalized facility name."""
    raw = json.loads(path.read_text())
    return {normalize(k): normalize(v) for k, v in raw.items() if not k.startswith("_")}


def match_to_hospitals(rows: list[dict], hospitals: list[dict], aliases: dict[str, str]) -> list[dict]:
    """Attach a facility_id (and match score) to each scraped row that confidently belongs to a hospital.

    A row matches when it is in the alias file, or when every distinctive word of the scraped name
    appears in exactly one hospital's name with a clear lead over the runner-up. Anything else stays
    unmatched on purpose: a missing wait time is better than one from another city's hospital.
    """
    by_norm = {normalize(h["name"]): h["id"] for h in hospitals}
    words = [(h["id"], distinctive_words(h["name"])) for h in hospitals]
    out = []
    for row in rows:
        target = aliases.get(normalize(row["name"]))
        if target is not None:
            fid = by_norm.get(target)
            if fid is None:
                log.warning("alias target not found among hospitals: '%s' -> '%s'", row["name"], target)
                continue
            out.append({**row, "facility_id": fid, "score": 1.0})
            continue
        sw = distinctive_words(row["name"])
        if not sw:
            continue
        cands = sorted(((len(sw & fw) / len(sw | fw), fid) for fid, fw in words if sw <= fw), reverse=True)
        if cands and cands[0][0] >= MIN_JACCARD and (len(cands) == 1 or cands[0][0] - cands[1][0] >= MIN_MARGIN):
            out.append({**row, "facility_id": cands[0][1], "score": cands[0][0]})
    return out


# ── consolidate ───────────────────────────────────────────────────────────────

def _best_per_facility(matched: list[dict]) -> dict[str, dict]:
    """One row per facility for a single source: prefer a live value, then a predicted range, then the better match."""
    def rank(r: dict) -> tuple:
        return (r["wait_minutes"] is not None, bool(r.get("predicted_text")), r["score"])

    best: dict[str, dict] = {}
    for r in matched:
        cur = best.get(r["facility_id"])
        if cur is None or rank(r) > rank(cur):
            best[r["facility_id"]] = r
    return best


def consolidate(erstat: list[dict], hlwiw: list[dict]) -> list[dict]:
    """Merge the two (already matched) sources into one record per facility."""
    er, hw = _best_per_facility(erstat), _best_per_facility(hlwiw)
    scraped_at = datetime.now(timezone.utc).isoformat()
    records = []
    for fid in sorted(set(er) | set(hw)):
        picks = [(s, r) for s, r in (("erstat", er.get(fid)), ("howlongwilliwait", hw.get(fid))) if r]
        live = [(s, r) for s, r in picks if r["wait_minutes"] is not None]
        predicted = [(s, r) for s, r in picks if r.get("predicted_text")]
        if live:  # live data always wins; a predicted range is never averaged into it
            minutes = round(sum(r["wait_minutes"] for _, r in live) / len(live))
            if len(live) == 2:
                raw, source = f"erstat:{live[0][1]['raw_wait']} / hlwiw:{live[1][1]['raw_wait']}", "erstat+howlongwilliwait"
            else:
                source, raw = live[0][0], live[0][1]["raw_wait"]
            is_predicted = False
        elif predicted:  # no number to give: keep the range as display text
            minutes, is_predicted = None, True
            source, raw = predicted[0][0], predicted[0][1]["predicted_text"]
        else:
            minutes, is_predicted = None, False
            source, raw = "+".join(s for s, _ in picks), picks[0][1]["raw_wait"]
        records.append({"facility_id": fid, "wait_minutes": minutes, "predicted": is_predicted,
                        "raw_wait": raw, "source": source, "scraped_at": scraped_at})
    return records


# ── sinks: one batched write each ─────────────────────────────────────────────

UPSERT_WAIT_TIMES = """
insert into wait_times (facility_id, wait_minutes, predicted, raw_wait, source, scraped_at)
select * from unnest(%s::uuid[], %s::int[], %s::bool[], %s::text[], %s::text[], %s::timestamptz[])
on conflict (facility_id) do update set
    wait_minutes = excluded.wait_minutes, predicted = excluded.predicted, raw_wait = excluded.raw_wait,
    source = excluded.source, scraped_at = excluded.scraped_at, recorded_at = now()
where excluded.scraped_at >= wait_times.scraped_at
"""


def _live(records: list[dict]) -> list[dict]:
    return [r for r in records if r["wait_minutes"] is not None]


def _publishable(records: list[dict]) -> list[dict]:
    # the demo table holds live waits and flagged predicted ranges; "no data" only goes to Redis,
    # where it clears a stale value
    return [r for r in records if r["wait_minutes"] is not None or r["predicted"]]


def read_hospitals(dsn: str) -> list[dict]:
    with psycopg.connect(dsn, connect_timeout=10) as conn:
        rows = conn.execute("select id::text, name from facilities where category = 'hospital'").fetchall()
    return [{"id": r[0], "name": r[1]} for r in rows]


def write_postgres(dsn: str, records: list[dict]) -> int:
    rows = _publishable(records)
    if not rows:
        return 0
    cols = list(zip(*[(r["facility_id"], r["wait_minutes"], r["predicted"], r["raw_wait"], r["source"], r["scraped_at"])
                      for r in rows]))
    with psycopg.connect(dsn, connect_timeout=10) as conn:
        conn.execute(UPSERT_WAIT_TIMES, [list(c) for c in cols])
    return len(rows)


def write_supabase(url: str, key: str, records: list[dict]) -> int:
    rows = _live(records)  # Supabase's table has NOT NULL minutes and no predicted column (left untouched)
    if not rows:
        return 0
    headers = {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json", "Prefer": "return=minimal"}
    payload = [{k: r[k] for k in ("facility_id", "wait_minutes", "raw_wait", "source", "scraped_at")} for r in rows]
    requests.post(f"{url}/rest/v1/wait_times", headers=headers, json=payload, timeout=15).raise_for_status()
    return len(rows)


def write_redis(client: redis.Redis, records: list[dict]) -> int:
    """Hash `wait_times:current`, field = facility uuid, value = JSON. One pipeline round trip."""
    if not records:
        return 0
    pipe = client.pipeline()
    for r in records:
        pipe.hset(REDIS_HASH_KEY, r["facility_id"], json.dumps({
            "wait_minutes": r["wait_minutes"], "predicted": r["predicted"], "raw_wait": r["raw_wait"],
            "source": r["source"], "updated_at": r["scraped_at"],
        }))
    pipe.execute()
    return len(records)


# ── entry point ───────────────────────────────────────────────────────────────

def _fatal(message: str, exc: BaseException | None = None) -> None:
    log.error(message)
    if exc is not None:
        sentry_sdk.capture_exception(exc)
    else:
        sentry_sdk.capture_message(message, level="error")
    sentry_sdk.flush(timeout=3)
    sys.exit(1)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="read, scrape and match; write nothing")
    args = parser.parse_args(argv)

    dsn = os.environ.get("SENTRY_DSN_BACKEND") or os.environ.get("SENTRY_DSN")
    if dsn:
        sentry_sdk.init(dsn=dsn, traces_sample_rate=0, server_name="wait-time-worker")
    else:
        log.warning("no Sentry DSN set: failures will only appear in the Railway logs")

    missing = [k for k in REQUIRED_ENV if not os.environ.get(k, "").strip()]
    if missing:
        _fatal(f"missing environment variables: {', '.join(missing)}")
    env = {k: os.environ[k].strip() for k in REQUIRED_ENV}

    log.info("═══ Scraper run started%s ═══", " (dry run)" if args.dry_run else "")
    try:
        hospitals = read_hospitals(env["POSTGRES_DB_URL_WORKER"])
    except Exception as e:
        _fatal(f"could not read hospitals from Postgres: {e}", e)
    if not hospitals:
        _fatal("no hospital-category facilities in Postgres: refusing to run")

    erstat_all, hlwiw_all = scrape_erstat(), scrape_howlongwilliwait()
    if not erstat_all and not hlwiw_all:
        _fatal("both scrapers returned nothing")

    aliases = load_aliases()
    erstat = match_to_hospitals(erstat_all, hospitals, aliases)
    hlwiw = match_to_hospitals(hlwiw_all, hospitals, aliases)
    records = consolidate(erstat, hlwiw)
    live = len(_live(records))
    predicted = sum(1 for r in records if r["predicted"])
    unmatched = len(erstat_all) + len(hlwiw_all) - len(erstat) - len(hlwiw)
    log.info("Match: %d/%d hospitals have a scraped entry (%d live, %d predicted range); %d scraped names unmatched",
             len(records), len(hospitals), live, predicted, unmatched)

    if len(records) < MIN_MATCHED_HOSPITALS:
        _fatal(f"only {len(records)} hospitals matched (minimum {MIN_MATCHED_HOSPITALS}): sources or matching broke, nothing written")

    if args.dry_run:
        names = {h["id"]: h["name"] for h in hospitals}
        for r in records:
            shown = str(r["wait_minutes"]) if r["wait_minutes"] is not None else (f"~{r['raw_wait']}" if r["predicted"] else "none")
            log.info("  %-52s %-14s %s", names[r["facility_id"]][:52], shown, r["source"])
        known = {normalize(x["name"]) for x in erstat + hlwiw}
        log.info("unmatched (first 25): %s", [x["name"] for x in erstat_all + hlwiw_all if normalize(x["name"]) not in known][:25])
        log.info("═══ Dry run complete: nothing written ═══")
        return

    sinks = {
        "postgres": lambda: write_postgres(env["POSTGRES_DB_URL_WORKER"], records),
        "supabase": lambda: write_supabase(env["SUPABASE_URL"], env["SUPABASE_SERVICE_ROLE_KEY"], records),
        "redis": lambda: write_redis(redis.from_url(env["UPSTASH_REDIS_URL"], decode_responses=True), records),
    }
    failed = []
    for name, write in sinks.items():  # independent: one failing never blocks the others
        try:
            log.info("%s: wrote %d rows", name, write())
        except Exception as e:
            failed.append(name)
            log.error("%s sink failed: %s", name, e)
            sentry_sdk.capture_exception(e)
    sentry_sdk.flush(timeout=3)
    if failed:
        log.error("═══ Scraper run FAILED: sinks down: %s ═══", ", ".join(failed))
        sys.exit(1)
    log.info("═══ Scraper run complete — %d records published ═══", len(records))


if __name__ == "__main__":
    main()
