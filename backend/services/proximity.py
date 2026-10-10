import math
import os
from cache import get_cached_facilities


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    R = 6371.0
    φ1, φ2 = math.radians(lat1), math.radians(lat2)
    Δφ = math.radians(lat2 - lat1)
    Δλ = math.radians(lng2 - lng1)
    a = math.sin(Δφ / 2) ** 2 + math.cos(φ1) * math.cos(φ2) * math.sin(Δλ / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def find_nearest_facilities(
    lat: float,
    lng: float,
    severity: str,
    top_n: int | None = None,
) -> list[dict] | None:
    """
    Returns up to top_n nearest facilities that accept the given severity,
    sorted by Haversine distance ascending.

    - First item is always the nearest by straight-line distance.
    - All items include a computed `distanceKm` field.
    - Returns None if the facilities cache is empty.
    - Returns empty list if no facility accepts this severity.
    - top_n defaults to TRIAGE_TOP_N_FACILITIES env var (default 3).

    The full list is returned to the frontend so that Task 010 can later
    re-rank by Geoapify ETA without any backend change.
    """
    if top_n is None:
        top_n = int(os.environ.get("TRIAGE_TOP_N_FACILITIES", "3"))

    facilities, _ = get_cached_facilities()
    if facilities is None:
        return None

    eligible = [
        f for f in facilities
        if severity in f.get("accepted_severity", [])
    ]
    if not eligible:
        return []

    def with_distance(f: dict) -> dict:
        d = haversine_km(lat, lng, f["lat"], f["lng"])
        return {**f, "distanceKm": round(d, 2)}

    ranked = sorted(
        [with_distance(f) for f in eligible],
        key=lambda x: x["distanceKm"],
    )
    return ranked[:top_n]

# Same speeds (metres per second) as the Supabase function nearby_facilities(), so the demo branch
# of GET /facilities/nearby keeps the response contract. The web app does not display these fields.
WALK_MPS, TRANSIT_MPS, DRIVE_MPS = 1.4, 6.0, 11.0
MAX_RADIUS_M = 50000
NEARBY_LIMIT = 50


def find_facilities_within(
    lat: float,
    lng: float,
    radius_m: int,
    category: str | None = None,
) -> list[dict] | None:
    """
    Facilities within radius_m of the point, nearest first, in the NearbyFacilityResult shape.
    Reads the in-memory facility cache (operational facilities only). Returns None when the
    cache is empty.
    """
    facilities, _ = get_cached_facilities()
    if not facilities:
        return None

    radius = min(radius_m, MAX_RADIUS_M)
    rows: list[dict] = []
    for f in facilities:
        if category is not None and f.get("category") != category:
            continue
        if f.get("lat") is None or f.get("lng") is None:
            continue
        distance_m = round(haversine_km(lat, lng, f["lat"], f["lng"]) * 1000)
        if distance_m > radius:
            continue
        rows.append({
            "facility_id":     str(f["id"]),
            "facility_name":   f["name"],
            "category":        f["category"],
            "address":         f.get("address") or "",
            "phone":           f.get("phone"),
            "is_operational":  True,
            "distance_m":      distance_m,
            "eta_walk_min":    round(distance_m / WALK_MPS / 60),
            "eta_transit_min": round(distance_m / TRANSIT_MPS / 60),
            "eta_drive_min":   round(distance_m / DRIVE_MPS / 60),
        })

    rows.sort(key=lambda row: row["distance_m"])
    return rows[:NEARBY_LIMIT]
