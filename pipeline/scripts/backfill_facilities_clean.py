#!/usr/bin/env python3
"""
Local backfill: repopulate `facilities` enrichment columns via Geoapify,
then rebuild `facilities_clean` from them.

Merges places-enricher (Geoapify fetch) + places-processor (DB write)
into a single local loop. Supabase is reached via PostgREST API
(SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY).

Usage:
    source /home/niki/Documents/workenv/pydev/bin/activate
    doppler run -- python pipeline/scripts/backfill_facilities_clean.py [--limit N] [--dry-run] [--skip-clean-rebuild]

Reads SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, and GEOAPIFY_API_KEY from Doppler.
"""
import argparse
import json
import logging
import os
import random
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

import requests

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
logger = logging.getLogger('backfill_facilities_clean')

GEOAPIFY_SEARCH_URL  = 'https://api.geoapify.com/v1/geocode/search'
GEOAPIFY_DETAILS_URL = 'https://api.geoapify.com/v2/place-details'

SUPABASE_URL = os.environ['SUPABASE_URL'].rstrip('/')
SUPABASE_KEY = os.environ.get('SUPABASE_SERVICE_ROLE_KEY') or os.environ.get('VITE_SUPABASE_ANON_KEY', '')

SB_HEADERS = {
    'apikey':        SUPABASE_KEY,
    'Authorization': f'Bearer {SUPABASE_KEY}',
    'Content-Type':  'application/json',
}

WORKER_COUNT = int(os.environ.get('WORKER_COUNT', '4'))
PAGE_SIZE    = 1000
BATCH_SIZE   = 200


# ── global rate limiter — 5 req/sec cap for Geoapify free tier ─────────────
class RateLimiter:
    def __init__(self, max_per_sec: int):
        self.max_per_sec = max_per_sec
        self.lock = threading.Lock()
        self.timestamps = deque()

    def acquire(self):
        with self.lock:
            now = time.monotonic()
            while self.timestamps and now - self.timestamps[0] > 1:
                self.timestamps.popleft()
            if len(self.timestamps) >= self.max_per_sec:
                time.sleep(max(1 - (now - self.timestamps[0]), 0))
            self.timestamps.append(time.monotonic())


_rate_limiter = RateLimiter(max_per_sec=5)


# ── Geoapify places api ───────────────────────────────────────────────────

def _geoapify_get_with_retry(url: str, params: dict, max_retries: int = 5) -> requests.Response:
    backoff = 1.0
    for attempt in range(max_retries + 1):
        _rate_limiter.acquire()
        resp = requests.get(url, params=params, timeout=10)

        if resp.status_code == 429 or resp.status_code >= 500:
            if attempt == max_retries:
                resp.raise_for_status()
            retry_after = resp.headers.get('Retry-After')
            wait_time = float(retry_after) if (retry_after and retry_after.isdigit()) else backoff
            wait_time += random.uniform(0.1, 0.5)
            logger.warning(f"Geoapify HTTP {resp.status_code} on attempt {attempt + 1}. Retrying in {wait_time:.2f}s...")
            time.sleep(wait_time)
            backoff *= 2.0
        else:
            resp.raise_for_status()
            return resp
    return resp


def search_facility_geoapify(api_key: str, facility: dict) -> dict | None:
    query = f"{facility['name']} {facility.get('address', '')}".strip()
    params = {'text': query, 'apiKey': api_key, 'limit': 1}
    resp = _geoapify_get_with_retry(GEOAPIFY_SEARCH_URL, params)
    features = resp.json().get('features', [])
    if not features:
        logger.warning(f"No Geoapify match for {facility['name']}")
        return None
    return features[0].get('properties', {})


def fetch_place_details_geoapify(api_key: str, place_id: str) -> dict | None:
    params = {'id': place_id, 'apiKey': api_key}
    resp = _geoapify_get_with_retry(GEOAPIFY_DETAILS_URL, params)
    features = resp.json().get('features', [])
    if not features:
        return None
    return features[0].get('properties', {})


def _format_opening_hours(hours: str | list | dict | None) -> str | None:
    if not hours:
        return None
    if isinstance(hours, str):
        return json.dumps([hours])
    if isinstance(hours, list):
        return json.dumps(hours)
    if isinstance(hours, dict):
        return json.dumps([hours.get('display', str(hours))])
    return None


def build_record_geoapify(facility: dict, props: dict) -> dict:
    contact = props.get('contact', {})
    phone = contact.get('phone') or props.get('phone')
    hours_raw = props.get('opening_hours')

    business_status = 'OPERATIONAL'
    is_operational = True

    return {
        'facility_id':     facility['id'],
        'phone':           phone,
        'business_status': business_status,
        'is_operational':  is_operational,
        'weekday_hours':   _format_opening_hours(hours_raw),
        'scraped_address': props.get('formatted', facility.get('address')),
        'scraped_at':      datetime.now(timezone.utc).isoformat(),
        'fsq_place_id':    props.get('place_id'),
    }


def enrich_facility_geoapify(api_key: str, facility: dict) -> dict:
    place_id = facility.get('google_place_id')
    details = None
    if place_id and len(place_id) > 40:  # Check if cached place_id is a Geoapify ID
        details = fetch_place_details_geoapify(api_key, place_id)
    if not details:
        props = search_facility_geoapify(api_key, facility)
        if not props:
            raise ValueError('no_geoapify_match')
        place_id = props.get('place_id')
        if place_id:
            details = fetch_place_details_geoapify(api_key, place_id) or props
        else:
            details = props

    return {'record': build_record_geoapify(facility, details)}


# ── supabase rest — facilities ──────────────────────────────────────────

def fetch_stale_facilities(limit: int | None) -> list[dict]:
    """Facilities missing enrichment or stale (>7 days)."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    rows: list[dict] = []
    offset = 0
    while True:
        params = {
            'select': 'id,name,address,google_place_id',
            'or':     f'(google_place_id.is.null,last_enriched_at.is.null,last_enriched_at.lt.{cutoff})',
            'order':  'id',
            'offset': offset,
            'limit':  min(PAGE_SIZE, limit - len(rows)) if limit else PAGE_SIZE,
        }
        resp = requests.get(f'{SUPABASE_URL}/rest/v1/facilities', headers=SB_HEADERS, params=params, timeout=30)
        resp.raise_for_status()
        page = resp.json()
        rows.extend(page)
        if len(page) < PAGE_SIZE or (limit and len(rows) >= limit):
            break
        offset += PAGE_SIZE
    return rows[:limit] if limit else rows


def _patch_fields(record: dict) -> dict:
    """UPDATE-only semantics for business columns."""
    now = datetime.now(timezone.utc).isoformat()
    fields = {
        'phone':            record.get('phone'),
        'business_status':  record.get('business_status'),
        'weekday_hours':    record.get('weekday_hours'),
        'google_place_id':  record.get('fsq_place_id'),
        'last_enriched_at': record.get('scraped_at'),
        'updated_at':       now,
    }
    return {k: v for k, v in fields.items() if v is not None}


def patch_facility(record: dict) -> None:
    fields = _patch_fields(record)
    if not fields:
        return
    url  = f"{SUPABASE_URL}/rest/v1/facilities?id=eq.{record['facility_id']}"
    resp = requests.patch(url, headers=SB_HEADERS, json=fields, timeout=10)
    resp.raise_for_status()


# ── supabase rest — facilities_clean rebuild (mirrors facilities_clean.sql) ─

CLEAN_SELECT_COLS = (
    'id,name,category,source_facility_type,accepted_severity,address,lat,lng,'
    'phone,google_place_id,business_status,weekday_hours,last_enriched_at'
)


def fetch_enriched_facilities() -> list[dict]:
    """All facilities eligible for facilities_clean."""
    rows: list[dict] = []
    offset = 0
    while True:
        params = {
            'select':          CLEAN_SELECT_COLS,
            'google_place_id': 'not.is.null',
            'business_status': 'not.is.null',
            'order':           'id',
            'offset':          offset,
            'limit':           PAGE_SIZE,
        }
        resp = requests.get(f'{SUPABASE_URL}/rest/v1/facilities', headers=SB_HEADERS, params=params, timeout=30)
        resp.raise_for_status()
        page = resp.json()
        rows.extend(page)
        if len(page) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
    return rows


def build_clean_record(facility: dict) -> dict:
    status = (facility.get('business_status') or '').upper()
    return {
        'facility_id':          facility['id'],
        'facility_name':        (facility.get('name') or '').strip(),
        'category':             facility.get('category'),
        'source_facility_type': facility.get('source_facility_type'),
        'accepted_severity':    facility.get('accepted_severity'),
        'address':              facility.get('address'),
        'lat':                  facility.get('lat'),
        'lng':                  facility.get('lng'),
        'phone':                facility.get('phone'),
        'google_place_id':      facility.get('google_place_id'),
        'business_status':      status,
        'is_operational':       status == 'OPERATIONAL',
        'weekday_hours':        facility.get('weekday_hours'),
        'last_enriched_at':     facility.get('last_enriched_at'),
        'dbt_run_at':           datetime.now(timezone.utc).isoformat(),
    }


def rebuild_facilities_clean() -> None:
    facilities = fetch_enriched_facilities()
    records = [build_clean_record(f) for f in facilities]
    logger.info(f'Rebuilding facilities_clean with {len(records)} enriched facilities')
    if not records:
        logger.warning('Nothing enriched — leaving facilities_clean untouched')
        return

    del_resp = requests.delete(f'{SUPABASE_URL}/rest/v1/facilities_clean',
                                headers=SB_HEADERS, params={'facility_id': 'not.is.null'}, timeout=30)
    del_resp.raise_for_status()

    for i in range(0, len(records), BATCH_SIZE):
        batch = records[i:i + BATCH_SIZE]
        resp = requests.post(f'{SUPABASE_URL}/rest/v1/facilities_clean', headers=SB_HEADERS, json=batch, timeout=30)
        resp.raise_for_status()
    logger.info(f'facilities_clean: inserted {len(records)} rows')


# ── main ─────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--limit', type=int, default=None, help='cap facilities fetched, for testing')
    parser.add_argument('--dry-run', action='store_true', help='fetch from Geoapify but do not write to Supabase')
    parser.add_argument('--skip-clean-rebuild', action='store_true', help='skip the facilities_clean rebuild step')
    args = parser.parse_args()

    api_key = os.environ.get('GEOAPIFY_API_KEY') or os.environ.get('VITE_GEOAPIFY_API_KEY')
    if not api_key:
        raise ValueError("GEOAPIFY_API_KEY not found in environment.")

    facilities = fetch_stale_facilities(args.limit)
    logger.info(f'Fetched {len(facilities)} facilities to enrich')

    errors  = []
    updated = 0
    if facilities:
        with ThreadPoolExecutor(max_workers=WORKER_COUNT) as executor:
            futures = {
                executor.submit(enrich_facility_geoapify, api_key, facility): facility
                for facility in facilities
            }
            for future in as_completed(futures):
                facility = futures[future]
                try:
                    result = future.result()
                    if not args.dry_run:
                        patch_facility(result['record'])
                    updated += 1
                    if updated % 25 == 0:
                        logger.info(f'{updated}/{len(facilities)} enriched')
                except Exception as e:
                    logger.error(f"Failed on {facility['name']}: {e}")
                    errors.append({'facility_id': facility['id'], 'reason': str(e)})

        logger.info(f'Done — {updated} updated, {len(errors)} errors')
        if errors:
            logger.info(f'Errors: {json.dumps(errors, indent=2)}')

    if not args.dry_run and not args.skip_clean_rebuild:
        rebuild_facilities_clean()


if __name__ == '__main__':
    main()
