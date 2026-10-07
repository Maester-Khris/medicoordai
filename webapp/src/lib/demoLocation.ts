import type { AppConfig } from "@shared/types"

export interface LatLng {
  lat: number
  lng: number
}

// The demo's facilities are all in Toronto; a position outside this box gives a useless recommendation.
const TORONTO_BOX = { minLat: 43.58, maxLat: 43.86, minLng: -79.64, maxLng: -79.12 }

export const FALLBACK_NOTICE = "Using downtown Toronto as your location"

export function isInToronto({ lat, lng }: LatLng): boolean {
  return lat >= TORONTO_BOX.minLat && lat <= TORONTO_BOX.maxLat
    && lng >= TORONTO_BOX.minLng && lng <= TORONTO_BOX.maxLng
}

/** In demo mode, a missing or out-of-town position is replaced by downtown Toronto. */
export function resolveDemoCoords(
  coords: LatLng | null,
  config: AppConfig,
): { coords: LatLng | null; usedFallback: boolean } {
  if (!config.demo_mode) return { coords, usedFallback: false }
  if (coords && isInToronto(coords)) return { coords, usedFallback: false }
  return { coords: config.downtown_fallback, usedFallback: true }
}
