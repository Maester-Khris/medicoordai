"""
Spatial index using Uber H3 hexagonal cells for fast proximity lookups.
Avoids scanning every facility by partitioning coordinates into discrete H3 cells
and querying concentric hexagonal rings around the guest's location.
"""
import math
from typing import Callable
import h3

# Resolution 8 produces ~0.46 km average edge length hexagons, balancing cell count and search radius.
RESOLUTION: int = 8
# Hexagon edge bounds in km at resolution 8, bounding center-to-center distances between cells.
EDGE_KM_MIN: float = 0.35
EDGE_KM_MAX: float = 0.60
# Upper limit on search rings; beyond 40 rings a full linear scan is cheaper and prevents unbounded index walks.
MAX_RINGS: int = 40
# Measured, below about 1,000 facilities the scan is as fast or faster (0.12 ms for 304 facilities against 0.18 to 0.70 ms through the cells).
MIN_INDEXED: int = 1000

# Cache storage for lazy index construction across consecutive queries.
_cached_facilities: list[dict] | None = None
_cell_index: dict[str, list[tuple[int, dict]]] = {}


def cell_of(lat: float, lng: float, resolution: int = RESOLUTION) -> str:
    """
    Computes the H3 cell identifier for coordinates at the given resolution
    so facilities and query points can be mapped to discrete spatial buckets.
    """
    return h3.latlng_to_cell(lat, lng, resolution)


def _get_index(facilities: list[dict]) -> dict[str, list[tuple[int, dict]]]:
    """
    Builds the cell-to-facilities index lazily, rebuilding only when the facilities list
    instance changes (checked via object identity `is`) to avoid repeated indexing overhead.
    Facilities without latitude or longitude are skipped because they cannot be spatially indexed.
    """
    global _cached_facilities, _cell_index
    if _cached_facilities is not facilities:
        _cached_facilities = facilities
        index: dict[str, list[tuple[int, dict]]] = {}
        for pos, facility in enumerate(facilities):
            lat = facility.get("lat")
            lng = facility.get("lng")
            if lat is None or lng is None:
                continue
            cell = cell_of(lat, lng, RESOLUTION)
            if cell not in index:
                index[cell] = []
            index[cell].append((pos, facility))
        _cell_index = index
    return _cell_index


def rings_covering(distance_km: float) -> int:
    """
    Rings around a point's cell that are sure to contain everything within `distance_km`.
    Two cells g rings apart have centres at least 1.5 * edge * g apart, and a point is at most
    one edge from its cell centre; with the smallest and largest edge that gives
    distance >= 1.5 * EDGE_KM_MIN * g - 2 * EDGE_KM_MAX, solved here for g.
    """
    return math.floor((distance_km + 2 * EDGE_KM_MAX) / (1.5 * EDGE_KM_MIN)) + 1


def nearest(
    facilities: list[dict],
    lat: float,
    lng: float,
    accepts: Callable[[dict], bool],
    count: int,
    distance_km: Callable[[dict], float],
) -> list[tuple[int, dict]] | None:
    """
    Candidate lookup for nearest facilities using expanding H3 rings to minimize scanned facilities.
    Grows the disk through (1, 2, 4, 8, 16, 32, MAX_RINGS) until at least count accepted facilities
    are found. Returns None to signal the caller to fall back to a full scan when the index cannot
    guarantee all nearest candidates were found or when the facility list is too small to index.
    """
    if count < 1:
        return []
    if len(facilities) < MIN_INDEXED:
        return None

    center_cell = cell_of(lat, lng, RESOLUTION)
    index = _get_index(facilities)

    disk_steps = tuple(r for r in (1, 2, 4, 8, 16, 32) if r < MAX_RINGS) + (MAX_RINGS,)
    for k in disk_steps:
        disk_cells = h3.grid_disk(center_cell, k)
        accepted: list[tuple[int, dict]] = []
        for cell in disk_cells:
            entries = index.get(cell)
            if entries:
                for item in entries:
                    if accepts(item[1]):
                        accepted.append(item)

        if len(accepted) >= count:
            accepted.sort(key=lambda item: (distance_km(item[1]), item[0]))
            that = distance_km(accepted[count - 1][1])
            needed = rings_covering(that)
            if needed <= k:
                return accepted
            if needed > MAX_RINGS:
                return None
            needed_cells = h3.grid_disk(center_cell, needed)
            result: list[tuple[int, dict]] = []
            for cell in needed_cells:
                entries = index.get(cell)
                if entries:
                    for item in entries:
                        if accepts(item[1]):
                            result.append(item)
            return result

    return None


def within_radius(
    facilities: list[dict],
    lat: float,
    lng: float,
    radius_km: float,
) -> list[tuple[int, dict]] | None:
    """
    Returns candidate facilities within the H3 rings covering radius_km to avoid scanning
    the entire facility collection. Returns None if the facilities list is below MIN_INDEXED
    or if the required ring count exceeds MAX_RINGS, letting the caller fall back to a full scan.
    """
    if len(facilities) < MIN_INDEXED:
        return None
    rings = rings_covering(radius_km)
    if rings > MAX_RINGS:
        return None

    center_cell = cell_of(lat, lng, RESOLUTION)
    index = _get_index(facilities)
    disk_cells = h3.grid_disk(center_cell, rings)
    result: list[tuple[int, dict]] = []
    for cell in disk_cells:
        entries = index.get(cell)
        if entries:
            result.extend(entries)
    return result
