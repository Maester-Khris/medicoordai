import type { TriageUIState, FacilityCandidate } from '../../../../../shared/types'

const CARTO_KEY = import.meta.env.VITE_CARTO_API_KEY as string | undefined

export const cartoTileUrl = (style: 'rastertiles/voyager' | 'dark_all'): string =>
  `https://{s}.basemaps.cartocdn.com/${style}/{z}/{x}/{y}{r}.png${CARTO_KEY ? `?key=${CARTO_KEY}` : ''}`

export const cnTowerPos: [number, number] = [43.6426, -79.3871]

export const INACTIVE_TRIAGE: TriageUIState = {
  active:                false,
  severity:              null,
  reasoning:             null,
  recommendedFacility:   null,
  nearbyFacilities:      [],
  userCoords:            null,
  routes:                [],
  recommendedFacilityId: null,
  roadGeometry:          null,
  travelMode:            "car",
  routeLoading:          false,
}

export function buildTriageCandidates(triage: TriageUIState): FacilityCandidate[] {
  if (!triage.active) return []
  const list: FacilityCandidate[] = []
  if (triage.recommendedFacility) {
    list.push(triage.recommendedFacility)
  }
  for (const f of triage.nearbyFacilities) {
    const isRec = triage.recommendedFacility && (
      (triage.recommendedFacility.id && f.id && triage.recommendedFacility.id === f.id) ||
      (triage.recommendedFacility.name === f.name)
    )
    if (!isRec) {
      list.push(f)
    }
  }
  return list
}
