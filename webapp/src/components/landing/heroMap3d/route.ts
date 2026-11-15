import { ROUTE, type LngLat } from './config'

const clamp01 = (t: number): number => Math.max(0, Math.min(1, t))
export const easeInOut = (t: number): number => (t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2)
export { clamp01 }

// Cumulative length along the route in metres (flat-earth approximation is plenty at this scale).
const routeDist: number[] = (() => {
  const mPerLat = 111320
  const mPerLng = 111320 * Math.cos((43.65 * Math.PI) / 180)
  const out = [0]
  for (let i = 1; i < ROUTE.length; i++) {
    const dx = (ROUTE[i][0] - ROUTE[i - 1][0]) * mPerLng
    const dy = (ROUTE[i][1] - ROUTE[i - 1][1]) * mPerLat
    out.push(out[i - 1] + Math.hypot(dx, dy))
  }
  return out
})()

// The first `progress` (0..1) of the route as a coordinate list.
function routeSlice(progress: number): LngLat[] {
  const total = routeDist[routeDist.length - 1]
  const target = clamp01(progress) * total
  const coords: LngLat[] = [ROUTE[0]]
  for (let i = 1; i < ROUTE.length; i++) {
    if (routeDist[i] <= target) {
      coords.push(ROUTE[i])
      continue
    }
    const seg = routeDist[i] - routeDist[i - 1]
    const f = seg ? (target - routeDist[i - 1]) / seg : 0
    coords.push([
      ROUTE[i - 1][0] + (ROUTE[i][0] - ROUTE[i - 1][0]) * f,
      ROUTE[i - 1][1] + (ROUTE[i][1] - ROUTE[i - 1][1]) * f,
    ])
    break
  }
  if (coords.length < 2) coords.push(ROUTE[0])
  return coords
}

export interface RouteFeature {
  type: 'Feature'
  properties: Record<string, never>
  geometry: { type: 'LineString'; coordinates: LngLat[] }
}

export const routeGeoJson = (progress: number): RouteFeature => ({
  type: 'Feature',
  properties: {},
  geometry: { type: 'LineString', coordinates: routeSlice(progress) },
})
