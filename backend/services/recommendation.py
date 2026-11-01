"""
Load-aware facility recommendation ranking.
Nearest-first routing sends everyone in an area to the same facility on wait data up to
15 minutes old. Balancing distributes routine and moderate cases across nearby facilities
using travel time, posted wait times, and recent local recommendation assignments.
Urgent and emergent cases are never balanced: emergency care always routes strictly nearest-first.
"""
import random
from typing import Callable

import config
from services import facility_load, travel_time
from services.wait_cache import current_wait

# Severities eligible for load-aware balancing. Emergent and urgent always route nearest-first.
BALANCED_SEVERITIES: tuple[str, ...] = ("routine", "moderate")

# Assumed travel mode for initial candidate scoring before patient mode preference is known.
RANKING_MODE: str = "car"

# Starting penalty values in minutes per recent assignment with no capacity data behind them.
LOAD_PENALTY_MINUTES: dict[str, float] = {
    "hospital": 2.0,
    "ambulatory": 4.0,
    "residential": 4.0,
}
DEFAULT_LOAD_PENALTY_MINUTES: float = 3.0


def score_minutes(
    facility: dict,
    lat: float,
    lng: float,
    wait_map: dict[str, dict] | dict[str, object],
) -> float:
    """
    Calculates total estimated delay in minutes combining travel time, posted emergency
    room wait, and load penalty for recent recommendation volume to balance routine patients
    away from overwhelmed care sites.
    """
    facility_id = str(facility["id"])
    travel = travel_time.travel_minutes(lat, lng, facility, RANKING_MODE)

    wait_entry = wait_map.get(facility_id)
    wait_min = 0.0
    if isinstance(wait_entry, dict):
        raw_val = wait_entry.get("wait_minutes")
        if raw_val is not None:
            wait_min = float(raw_val)

    category = facility.get("category", "")
    penalty = LOAD_PENALTY_MINUTES.get(category, DEFAULT_LOAD_PENALTY_MINUTES)
    assignments = facility_load.recent_assignments(facility_id)

    return travel + wait_min + (assignments * penalty)


def rank_facilities(
    candidates: list[dict],
    severity: str,
    lat: float,
    lng: float,
    rng: Callable[[], float] = random.random,
) -> list[dict]:
    """
    Re-ranks candidate facilities considering estimated total delay and local load.
    Routine and moderate cases with close scores are randomized across tied options
    to distribute patient arrivals evenly instead of swamping a single nearest facility.
    """
    if len(candidates) < 2:
        return candidates
    if severity not in BALANCED_SEVERITIES:
        return candidates
    if not config.load_aware_routing():
        return candidates

    snapshot = current_wait()
    wait_map = snapshot.wait_map if snapshot is not None else {}

    scored = sorted(
        [
            (score_minutes(c, lat, lng, wait_map), i, c)
            for i, c in enumerate(candidates)
        ],
        key=lambda item: (item[0], item[1]),
    )

    best_score = scored[0][0]
    tie_band = config.env_int("LOAD_SCORE_TIE_MINUTES", 5, minimum=0, maximum=120)
    tied = [entry for entry in scored if entry[0] <= best_score + tie_band]

    pick_idx = min(int(rng() * len(tied)), len(tied) - 1)
    picked_entry = tied[pick_idx]
    picked_facility = picked_entry[2]

    others = [entry[2] for entry in scored if entry[1] != picked_entry[1]]
    return [picked_facility] + others
