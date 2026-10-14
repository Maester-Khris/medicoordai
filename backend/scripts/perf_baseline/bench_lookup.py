"""Times the nearest-facility lookup with and without the cell index, on synthetic facilities.

Run from backend/:  python -m scripts.perf_baseline.bench_lookup
Prints one row per facility count. No network, no database.
"""
import random
import time

from services import cell_index
from services.proximity import haversine_km

CENTRE = (43.6532, -79.3832)
SEVERITIES = ("routine", "moderate", "urgent", "emergent")
LOOKUPS = 200
TOP_N = 3


def synthetic(count: int, seed: int = 1, spread: float = 0.6) -> list[dict]:
    rng = random.Random(seed)
    return [
        {"id": f"f{i}", "name": f"Facility {i}",
         "lat": CENTRE[0] + rng.uniform(-spread, spread), "lng": CENTRE[1] + rng.uniform(-spread, spread),
         "accepted_severity": rng.sample(SEVERITIES, rng.randint(1, 4))}
        for i in range(count)
    ]


def _points(seed: int = 2) -> list[tuple[float, float, str]]:
    rng = random.Random(seed)
    return [(CENTRE[0] + rng.uniform(-0.5, 0.5), CENTRE[1] + rng.uniform(-0.5, 0.5), rng.choice(SEVERITIES))
            for _ in range(LOOKUPS)]


def scan(facilities: list[dict], lat: float, lng: float, severity: str) -> list[dict]:
    eligible = [f for f in facilities if severity in f["accepted_severity"]]
    return sorted(eligible, key=lambda f: haversine_km(lat, lng, f["lat"], f["lng"]))[:TOP_N]


def indexed(facilities: list[dict], lat: float, lng: float, severity: str) -> list[dict]:
    def distance(f: dict) -> float:
        return haversine_km(lat, lng, f["lat"], f["lng"])

    entries = cell_index.nearest(facilities, lat, lng, lambda f: severity in f["accepted_severity"], TOP_N, distance)
    pool = [f for f in facilities if severity in f["accepted_severity"]] if entries is None else [f for _, f in entries]
    return sorted(pool, key=distance)[:TOP_N]


def _mean_ms(lookup, facilities: list[dict], points: list[tuple[float, float, str]]) -> float:
    started = time.perf_counter()
    for lat, lng, severity in points:
        lookup(facilities, lat, lng, severity)
    return (time.perf_counter() - started) * 1000 / len(points)


def main() -> None:
    points = _points()
    print(f"{'facilities':>10}  {'scan ms':>9}  {'index ms':>9}  {'speedup':>8}")
    for count in (304, 10_000, 100_000):
        facilities = synthetic(count)
        indexed(facilities, *points[0])  # build the index outside the timing
        scan_ms = _mean_ms(scan, facilities, points)
        index_ms = _mean_ms(indexed, facilities, points)
        print(f"{count:>10}  {scan_ms:>9.3f}  {index_ms:>9.3f}  {scan_ms / index_ms:>7.1f}x")


if __name__ == "__main__":
    main()
