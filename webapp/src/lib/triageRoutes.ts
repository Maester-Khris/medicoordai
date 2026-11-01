import type {
  FacilityCandidate, RouteResult, RoutesResponse, TravelModeKey, TriageUIState,
} from "@shared/types"

function candidates(state: TriageUIState): FacilityCandidate[] {
  return state.recommendedFacility
    ? [state.recommendedFacility, ...state.nearbyFacilities]
    : []
}

/**
 * Ids sent to POST /routes: the recommended facility first, then the alternatives.
 * Truncates to `upFront` ids to minimize unnecessary routing API requests before user interaction.
 */
export function candidateIds(state: TriageUIState, upFront: number = Number.POSITIVE_INFINITY): string[] {
  return candidates(state).map(f => f.id).slice(0, upFront)
}

/** Candidates the backend could not route are dropped: a time is real or it is absent. */
export function toRouteResults(response: RoutesResponse): RouteResult[] {
  return response.routes.flatMap(route => {
    if (route.eta_minutes === null || route.distance_km === null) {
      return []
    }
    const result: RouteResult = {
      facilityId: route.facility_id,
      etaMinutes: route.eta_minutes,
      distanceKm: route.distance_km,
      geometry:   route.geometry,
    }
    if (route.estimated) {
      result.estimated = true
    }
    return [result]
  })
}

/**
 * Makes `facilityId` the recommended facility. The previous one joins the alternatives, so every
 * surface that reads `recommendedFacility` / `nearbyFacilities` agrees with the map.
 */
export function promoteFacility(state: TriageUIState, facilityId: string): TriageUIState {
  const all = candidates(state)
  const chosen = all.find(f => f.id === facilityId)
  if (!chosen) return state
  const route = state.routes.find(r => r.facilityId === facilityId)
  return {
    ...state,
    recommendedFacility:   chosen,
    nearbyFacilities:      all.filter(f => f.id !== facilityId),
    recommendedFacilityId: facilityId,
    roadGeometry:          route?.geometry ?? null,
  }
}

/**
 * Merges newly fetched routes into existing state.routes, replacing any existing route for the same facility.
 * Sets routeLoading to false and preserves the current recommendation and road geometry so the user's
 * view does not jump when background routes arrive.
 */
export function mergeRoutes(state: TriageUIState, response: RoutesResponse): TriageUIState {
  const incoming = toRouteResults(response)
  const incomingIds = new Set(incoming.map(r => r.facilityId))
  const preserved = state.routes.filter(r => !incomingIds.has(r.facilityId))
  return {
    ...state,
    routes: [...preserved, ...incoming],
    routeLoading: false,
  }
}

/** Applies a POST /routes answer: routes for `mode`, recommendation on the fastest candidate. */
export function applyRoutes(
  state: TriageUIState,
  mode: TravelModeKey,
  response: RoutesResponse,
): TriageUIState {
  const next: TriageUIState = {
    ...state,
    travelMode:   mode,
    routes:       toRouteResults(response),
    routeLoading: false,
  }
  return response.fastest_facility_id
    ? promoteFacility(next, response.fastest_facility_id)
    : { ...next, roadGeometry: null }
}

