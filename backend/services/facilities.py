import json as json_lib
import logging
from fastapi import HTTPException

import demo_db
from config import demo_mode
from db import supabase_select

logger = logging.getLogger(__name__)


DEMO_FACILITIES_SQL = """
    select id::text as id, name, category, source_facility_type, accepted_severity,
           address, lat, lng, phone, business_status, weekday_hours
    from facilities
    where is_operational
      and (%(category)s::text is null or category = %(category)s)
      and (%(severity)s::text is null or %(severity)s = any(accepted_severity))
    order by name
"""


def _parse_weekday_hours(rows: list[dict]) -> list[dict]:
    """weekday_hours is a text column storing a JSON array string; parse it in place."""
    for f in rows:
        wh = f.get("weekday_hours")
        if isinstance(wh, str):
            try:
                f["weekday_hours"] = json_lib.loads(wh)
            except (ValueError, TypeError):
                f["weekday_hours"] = []
        elif wh is None:
            f["weekday_hours"] = []
    return rows


def _supabase_facilities(category: str | None, severity: str | None) -> list[dict]:
    params = {
        "select": "id:facility_id,name:facility_name,category,source_facility_type,"
                  "accepted_severity,address,lat,lng,phone,business_status,weekday_hours",
        "is_operational": "eq.true",
    }
    if category is not None:
        params["category"] = f"eq.{category}"
    if severity is not None:
        params["accepted_severity"] = f"cs.{{{severity}}}"
    return supabase_select("facilities_clean", params) or []


def get_all_facilities(
    category: str | None = None,
    severity: str | None = None,
) -> list[dict]:
    try:
        if demo_mode():
            rows = demo_db.fetch_all(DEMO_FACILITIES_SQL, {"category": category, "severity": severity})
        else:
            rows = _supabase_facilities(category, severity)
        return _parse_weekday_hours(rows)
    except HTTPException:
        raise
    except Exception as e:
        logger.error("facilities_query_failed", extra={"error_type": type(e).__name__})
        raise HTTPException(status_code=503, detail="Database unavailable")


def apply_wait_filter(
    records: list[dict],
    id_key: str,
    max_wait_minutes: int | None,
    wait_map: dict[str, int | None],
) -> list[dict]:
    """
    Returns new records annotated with wait_minutes from wait_map (never
    mutates the input — callers may hold the same dict objects in a
    shared cache). When max_wait_minutes is set, drops records whose
    wait_minutes exceeds it — records with no wait data (None) always
    pass, same convention as the open_24h/open_weekends hours filters.
    """
    annotated = [{**r, "wait_minutes": wait_map.get(r[id_key])} for r in records]

    if max_wait_minutes is None:
        return annotated

    return [r for r in annotated if r["wait_minutes"] is None or r["wait_minutes"] <= max_wait_minutes]


def annotate_wait_details(records: list[dict], id_key: str, wait_map: dict[str, dict]) -> list[dict]:
    """Adds raw_wait (display text) and predicted to each record; never mutates the input."""
    annotated = []
    for r in records:
        info = wait_map.get(r[id_key], {})
        annotated.append({**r, "raw_wait": info.get("raw_wait"), "predicted": bool(info.get("predicted", False))})
    return annotated
