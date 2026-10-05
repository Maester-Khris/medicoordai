#!/usr/bin/env python3
"""Self-check for backfill_facilities_clean.py's pure logic — no network.
Run: python pipeline/scripts/test_backfill_facilities_clean.py
"""
import os
import time

os.environ.setdefault('SUPABASE_URL', 'https://example.supabase.co')
os.environ.setdefault('SUPABASE_SERVICE_ROLE_KEY', 'x')

import backfill_facilities_clean as b


def test_build_weekday_hours():
    hours = {'regular': [
        {'day': 1, 'open': '0800', 'close': '1700'},
        {'day': 1, 'open': '1800', 'close': '2000'},
    ]}
    out = b._build_weekday_hours_fsq(hours)
    assert out == '["Monday: 08:00 \\u2013 17:00, 18:00 \\u2013 20:00"]', out
    assert b._build_weekday_hours_fsq({}) is None
    assert b._build_weekday_hours_fsq({'display': 'Call for hours'}) == '["Call for hours"]'


def test_build_record_foursquare():
    facility = {'id': 'f1', 'name': 'Test Clinic', 'address': '1 Main St'}
    details = {
        'fsq_place_id': 'fsq123', 'tel': '555-1234',
        'location': {'formatted_address': '1 Main St, Toronto'},
        'hours': {}, 'date_closed': None,
    }
    record = b.build_record_foursquare(facility, details)
    assert record['facility_id'] == 'f1'
    assert record['business_status'] == 'OPERATIONAL'
    assert record['is_operational'] is True
    assert record['fsq_place_id'] == 'fsq123'

    closed = b.build_record_foursquare(facility, {**details, 'date_closed': '2024-01-01'})
    assert closed['business_status'] == 'CLOSED_PERMANENTLY'
    assert closed['is_operational'] is False


def test_patch_fields_drops_none():
    record = {'phone': '555', 'business_status': None, 'is_operational': True,
              'weekday_hours': None, 'fsq_place_id': 'abc', 'scraped_at': '2024-01-01'}
    fields = b._patch_fields(record)
    assert fields['phone'] == '555'
    assert fields['is_operational'] is True
    assert fields['google_place_id'] == 'abc'
    assert fields['last_enriched_at'] == '2024-01-01'
    assert 'business_status' not in fields
    assert 'weekday_hours' not in fields
    assert 'updated_at' in fields  # always stamped


def test_build_clean_record_mirrors_dbt_model():
    facility = {
        'id': 'f1', 'name': '  Test Clinic  ', 'category': 'clinic',
        'source_facility_type': 'walk-in', 'accepted_severity': 'moderate',
        'address': '1 Main St', 'lat': 43.6, 'lng': -79.4,
        'phone': '555', 'google_place_id': 'fsq123',
        'business_status': 'operational', 'weekday_hours': '[]',
        'last_enriched_at': '2024-01-01T00:00:00Z',
    }
    record = b.build_clean_record(facility)
    assert record['facility_id'] == 'f1'
    assert record['facility_name'] == 'Test Clinic'
    assert record['business_status'] == 'OPERATIONAL'
    assert record['is_operational'] is True

    closed = b.build_clean_record({**facility, 'business_status': 'CLOSED_PERMANENTLY'})
    assert closed['is_operational'] is False


def test_rate_limiter_caps_throughput():
    limiter = b.RateLimiter(max_per_sec=5)
    start = time.monotonic()
    for _ in range(10):
        limiter.acquire()
    elapsed = time.monotonic() - start
    assert elapsed >= 0.9, f"expected ~1s+ for 10 acquires at 5/s, got {elapsed:.2f}s"


if __name__ == '__main__':
    for name, fn in list(globals().items()):
        if name.startswith('test_'):
            fn()
            print(f'ok  {name}')
    print('all tests passed')
