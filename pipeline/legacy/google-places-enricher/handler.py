# LEGACY / DISABLED (2026-10): Google Places enrichment.
# The Google Places API key expired and the demo no longer uses Google data. Kept for reference only;
# it is NOT referenced by pipeline/infra/template.yaml (the PlacesEnricher resource is commented out there).
# Replacement: backend/scripts/demo_seed/enrich_facilities_geoapify.py (manual, gap-fill, Geoapify).
import json
import boto3
import requests
import os
import logging
import psycopg2
import psycopg2.extras
import threading
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# ── clients ────────────────────────────────────────────────────────────────
s3 = boto3.client('s3')

# ── config ─────────────────────────────────────────────────────────────────
S3_BUCKET         = os.environ['S3_BUCKET']
S3_PREFIX         = os.environ.get('S3_PREFIX', 'raw/places/')
GOOGLE_PLACES_KEY = os.environ['GOOGLE_PLACES_KEY']

DB_HOST     = os.environ['SUPABASE_HOST']
DB_USER     = os.environ['SUPABASE_DB_USER']
DB_PASSWORD = os.environ['SUPABASE_DB_PASSWORD']
DB_NAME     = os.environ.get('SUPABASE_DB_NAME', 'postgres')
DB_PORT     = int(os.environ.get('SUPABASE_DB_PORT', '5432'))

WORKER_COUNT = 10
# Limits concurrent Google Places API calls regardless of thread pool size
_api_semaphore = threading.Semaphore(WORKER_COUNT)
TMP_PATH       = '/tmp/places_records.ndjson'


# ── database ───────────────────────────────────────────────────────────────

def _get_db_conn():
    return psycopg2.connect(
        host=DB_HOST, user=DB_USER, password=DB_PASSWORD,
        dbname=DB_NAME, port=DB_PORT, sslmode='require'
    )


def fetch_facilities_from_db() -> list[dict]:
    """Return facilities that are unenriched or stale (older than 7 days)."""
    conn = _get_db_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT id, name, address, google_place_id
                FROM   facilities
                WHERE  google_place_id IS NULL
                    OR last_enriched_at IS NULL
                    OR last_enriched_at < NOW() - INTERVAL '7 days'
            """)
            return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


def bulk_update_place_ids(pairs: list[tuple[str, str]]) -> None:
    """Write back newly resolved google_place_ids to avoid re-resolving next run."""
    conn = _get_db_conn()
    try:
        with conn.cursor() as cur:
            psycopg2.extras.execute_batch(cur, """
                UPDATE facilities
                SET    google_place_id = %s
                WHERE  id = %s
                  AND  google_place_id IS NULL
            """, [(place_id, facility_id) for facility_id, place_id in pairs])
        conn.commit()
    finally:
        conn.close()


# ── google places api ──────────────────────────────────────────────────────

def search_place_id(facility: dict, api_key: str) -> str | None:
    """Resolve facility name + address to a Google Place ID."""
    url    = "https://maps.googleapis.com/maps/api/place/findplacefromtext/json"
    params = {
        "input":     f"{facility['name']} {facility['address']}",
        "inputtype": "textquery",
        "fields":    "place_id,name",
        "key":       api_key,
    }
    resp = requests.get(url, params=params, timeout=10)
    resp.raise_for_status()
    candidates = resp.json().get("candidates", [])
    if not candidates:
        logger.warning(f"No place_id found for {facility['name']}")
        return None
    return candidates[0]["place_id"]


def fetch_place_details(place_id: str, api_key: str) -> dict:
    """Fetch hours, phone, open_now, business_status from Places API."""
    url    = "https://maps.googleapis.com/maps/api/place/details/json"
    params = {
        "place_id": place_id,
        "fields":   (
            "name,formatted_address,formatted_phone_number,"
            "opening_hours,current_opening_hours,business_status"
        ),
        "key": api_key,
    }
    resp = requests.get(url, params=params, timeout=10)
    resp.raise_for_status()
    return resp.json().get("result", {})


def _normalize_hours(entries: list[str]) -> list[str]:
    """Strip Google Places API typographic Unicode before storage."""
    return [
        s.replace('\u202f', ' ')   # narrow no-break space
         .replace('\u2009', ' ')   # thin space
         .replace('\u2013', '-')   # en dash
        for s in entries
    ]

def build_record(facility: dict, details: dict) -> dict:
    hours        = details.get("opening_hours", {})
    weekday_text = _normalize_hours(hours.get("weekday_text", []))
    return {
        "facility_id":     facility["id"],
        "phone":           details.get("formatted_phone_number"),
        "business_status": details.get("business_status"),
        "weekday_hours":   json.dumps(weekday_text),
        "scraped_name":    details.get("name", facility["name"]),
        "scraped_address": details.get("formatted_address", facility["address"]),
        "scraped_at":      datetime.now(timezone.utc).isoformat(),
    }


# ── enrichment worker ──────────────────────────────────────────────────────

def enrich_facility(facility: dict, api_key: str) -> dict:
    """
    Resolve place_id if not cached, fetch details.
    Semaphore caps concurrent Google API calls at WORKER_COUNT.
    Returns {'record': dict, 'new_place_id': str | None}.
    """
    with _api_semaphore:
        place_id     = facility.get('google_place_id')
        new_place_id = None

        if not place_id:
            place_id = search_place_id(facility, api_key)
            if not place_id:
                raise ValueError('no_place_id')
            new_place_id = place_id

        details = fetch_place_details(place_id, api_key)
        return {
            'record':       build_record(facility, details),
            'new_place_id': new_place_id,
        }


# ── s3 upload ──────────────────────────────────────────────────────────────

def upload_to_s3(payload: dict) -> str:
    ts  = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H-%M-%SZ')
    key = f"{S3_PREFIX}{ts}.json"
    s3.put_object(
        Bucket      = S3_BUCKET,
        Key         = key,
        Body        = json.dumps(payload, indent=2),
        ContentType = 'application/json',
    )
    logger.info(f"Uploaded to s3://{S3_BUCKET}/{key}")
    return key


# ── handler ────────────────────────────────────────────────────────────────

def lambda_handler(event, context):
    logger.info("Starting Google Places enrichment")

    facilities = fetch_facilities_from_db()
    logger.info(f"Fetched {len(facilities)} facilities to enrich")

    new_place_ids = []  # (facility_id, place_id) pairs to write back
    errors        = []
    record_count  = 0

    # Stream completed records to /tmp as futures resolve (Option A).
    # Main thread is the sole writer — no lock needed.
    with open(TMP_PATH, 'w') as tmp_file:
        with ThreadPoolExecutor(max_workers=WORKER_COUNT) as executor:
            futures = {
                executor.submit(enrich_facility, facility, GOOGLE_PLACES_KEY): facility
                for facility in facilities
            }
            for future in as_completed(futures):
                facility = futures[future]
                try:
                    result = future.result()
                    tmp_file.write(json.dumps(result['record']) + '\n')
                    tmp_file.flush()
                    record_count += 1
                    if result['new_place_id']:
                        new_place_ids.append(
                            (facility['id'], result['new_place_id'])
                        )
                except Exception as e:
                    logger.error(f"Failed on {facility['name']}: {e}")
                    errors.append({
                        'facility_id': facility['id'],
                        'reason':      str(e),
                    })

    # Cache newly resolved place_ids so next run skips search_place_id
    if new_place_ids:
        logger.info(f"Caching {len(new_place_ids)} new place_ids to DB")
        bulk_update_place_ids(new_place_ids)

    # Read /tmp to build the single S3 payload
    with open(TMP_PATH, 'r') as f:
        records = [json.loads(line) for line in f if line.strip()]

    payload = {
        'meta': {
            'source':       'google_places',
            'fetched_at':   datetime.now(timezone.utc).isoformat(),
            'record_count': record_count,
            'error_count':  len(errors),
            'errors':       errors,
        },
        'records': records,
    }

    s3_key = upload_to_s3(payload)
    logger.info(f"Done — {record_count} records, {len(errors)} errors")

    return {
        'statusCode': 200,
        'body': {
            's3_key':       s3_key,
            'record_count': record_count,
            'error_count':  len(errors),
        },
    }
