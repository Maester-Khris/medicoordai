export interface LatLng { lat: number; lng: number }

const EARTH_KM = 6371

// Straight-line distance: no network call, cheap enough for a few hundred facilities.
export function haversineKm(a: LatLng, b: LatLng): number {
  const rad = (d: number) => (d * Math.PI) / 180
  const dLat = rad(b.lat - a.lat)
  const dLng = rad(b.lng - a.lng)
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(rad(a.lat)) * Math.cos(rad(b.lat)) * Math.sin(dLng / 2) ** 2
  return 2 * EARTH_KM * Math.asin(Math.sqrt(h))
}

export function sortByDistance<T extends LatLng>(items: readonly T[], origin: LatLng): { item: T; km: number }[] {
  return items
    .map(item => ({ item, km: haversineKm(origin, item) }))
    .sort((x, y) => {
      if (Number.isNaN(x.km)) return Number.isNaN(y.km) ? 0 : 1
      if (Number.isNaN(y.km)) return -1
      return x.km - y.km
    })
}
