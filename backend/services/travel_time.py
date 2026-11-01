"""
Measured times come from routes this process already asked Geoapify for;
they are remembered per origin cell, facility and travel mode for 15 minutes
in process memory, and only improve the ranking of candidates (a drawn route
always starts at the guest's own position).
"""
import time
from collections import OrderedDict
from services import cell_index
from services.proximity import DRIVE_MPS, TRANSIT_MPS, WALK_MPS, haversine_km

# Speed in metres per second for bicycle travel.
BIKE_MPS: float = 4.2

# Mapping of travel mode to nominal speed in metres per second, reusing speeds from proximity service.
SPEED_MPS: dict[str, float] = {
    "car": DRIVE_MPS,
    "bus": TRANSIT_MPS,
    "bike": BIKE_MPS,
    "walk": WALK_MPS,
}

# H3 resolution for origin coordinates (~174 m edge length) to bucket nearby starting points together.
ORIGIN_RESOLUTION: int = 9

# Maximum cache capacity to prevent unbounded memory growth in the process.
MAX_ENTRIES: int = 20000

# TTL in seconds (15 minutes) for remembered travel durations before expiring.
ENTRY_SECONDS: int = 900

# In-process cache of (cell, facility_id, mode) -> (minutes, timestamp) maintained in insertion order.
_cache: OrderedDict[tuple[str, str, str], tuple[float, float]] = OrderedDict()


def estimate_minutes(distance_km: float, mode: str) -> float:
    """
    Estimates travel time in minutes based on straight-line distance and the nominal
    speed for the chosen travel mode, providing a fast baseline when routing is not cached.
    """
    speed_mps = SPEED_MPS[mode]
    return (distance_km * 1000.0) / (speed_mps * 60.0)


def remember(
    lat: float,
    lng: float,
    facility_id: str | int,
    mode: str,
    minutes: float,
    now: float | None = None,
) -> None:
    """
    Stores a known travel duration for an origin cell, target facility ID, and transport mode
    so future lookups within the same area avoid repeated routing requests.
    """
    current_time = time.monotonic() if now is None else now
    key = (cell_index.cell_of(lat, lng, ORIGIN_RESOLUTION), str(facility_id), mode)
    if key in _cache:
        del _cache[key]
    _cache[key] = (float(minutes), current_time)
    while len(_cache) > MAX_ENTRIES:
        _cache.popitem(last=False)


def recall(
    lat: float,
    lng: float,
    facility_id: str | int,
    mode: str,
    now: float | None = None,
) -> float | None:
    """
    Retrieves a cached travel duration if present and still valid within ENTRY_SECONDS,
    dropping stale records and returning None so callers know to calculate an estimate.
    """
    current_time = time.monotonic() if now is None else now
    key = (cell_index.cell_of(lat, lng, ORIGIN_RESOLUTION), str(facility_id), mode)
    entry = _cache.get(key)
    if entry is None:
        return None
    minutes, timestamp = entry
    if current_time - timestamp > ENTRY_SECONDS:
        del _cache[key]
        return None
    return minutes


def travel_minutes(
    lat: float,
    lng: float,
    facility: dict,
    mode: str,
    now: float | None = None,
) -> float:
    """
    Returns the remembered route time if cached, otherwise falls back to the straight-line
    Haversine distance estimate to ensure lookups always yield a usable travel duration.
    """
    facility_id = facility.get("id")
    if facility_id is not None:
        recalled = recall(lat, lng, facility_id, mode, now=now)
        if recalled is not None:
            return recalled

    fac_lat = facility.get("lat")
    fac_lng = facility.get("lng")
    if fac_lat is None or fac_lng is None:
        return 0.0

    distance_km = haversine_km(lat, lng, fac_lat, fac_lng)
    return estimate_minutes(distance_km, mode)


def clear() -> None:
    """
    Clears all cached travel times, used during testing and cache invalidation.
    """
    _cache.clear()
