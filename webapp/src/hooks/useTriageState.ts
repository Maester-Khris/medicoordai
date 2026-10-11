import { useCallback, useRef, useState } from "react"
import type { RoutesResponse, TravelModeKey, TriageResult, TriageUIState } from "../../../shared/types"
import { getConfig } from "../lib/config"
import { postModeChanged, postRouteDrawn } from "../lib/guestEvents"
import { fetchRoutes } from "../lib/routesClient"
import { applyRoutes, candidateIds, mergeRoutes, promoteFacility } from "../lib/triageRoutes"

const DEFAULT_MODE: TravelModeKey = "car"

const DEFAULT_STATE: TriageUIState = {
  active: false,
  severity: null,
  reasoning: null,
  recommendedFacility: null,
  nearbyFacilities: [],
  userCoords: null,
  routes: [],
  recommendedFacilityId: null,
  roadGeometry: null,
  travelMode: DEFAULT_MODE,
  routeLoading: false,
}

function cacheKey(mode: TravelModeKey, ids: string[]): string {
  return `${mode}:${ids.join(",")}`
}

export function useTriageState() {
  const [triage, setTriage] = useState<TriageUIState>(DEFAULT_STATE)
  // The async actions below need the latest state, not the one captured when they started.
  const stateRef = useRef<TriageUIState>(DEFAULT_STATE)
  // Cache keyed by mode and requested facility ids to prevent collisions between single and multi-facility responses.
  const cacheRef = useRef(new Map<string, RoutesResponse>())
  // Bumped on every new request: an answer whose number is no longer current is dropped.
  const requestRef = useRef(0)
  const sessionRef = useRef<string | null>(null)

  const commit = useCallback((next: TriageUIState) => {
    stateRef.current = next
    setTriage(next)
  }, [])

  const reset = useCallback(() => {
    requestRef.current += 1
    cacheRef.current = new Map()
    sessionRef.current = null
    commit(DEFAULT_STATE)
  }, [commit])

  const applyTriageResult = useCallback(async (
    result: TriageResult,
    userCoords: { lat: number; lng: number } | null,
    sessionId?: string | null,
  ) => {
    const requestId = ++requestRef.current
    cacheRef.current = new Map()
    sessionRef.current = sessionId ?? null

    if (!result.recommended_facility) {
      commit({
        ...DEFAULT_STATE,
        active: true,
        severity: result.severity,
        reasoning: result.reasoning,
        nearbyFacilities: result.nearby_facilities,
        userCoords,
      })
      return
    }

    const base: TriageUIState = {
      ...DEFAULT_STATE,
      active: true,
      severity: result.severity,
      reasoning: result.reasoning,
      recommendedFacility: result.recommended_facility,
      nearbyFacilities: result.nearby_facilities,
      userCoords,
      recommendedFacilityId: result.recommended_facility.id,
      routeLoading: userCoords !== null,
    }
    commit(base)
    if (!userCoords) return

    // Limit initial routing requests up front to save provider quota and reduce guest wait times.
    const upFront = (await getConfig()).routes_up_front ?? 1
    if (requestId !== requestRef.current) return

    const ids = candidateIds(base, upFront)
    const response = await fetchRoutes(userCoords, ids, DEFAULT_MODE, result.severity)
    if (requestId !== requestRef.current) return
    if (!response) {
      commit({ ...stateRef.current, routeLoading: false })
      return
    }
    cacheRef.current.set(cacheKey(DEFAULT_MODE, ids), response)
    const next = applyRoutes(stateRef.current, DEFAULT_MODE, response)
    commit(next)
    // Only real road geometry counts as "route drawn"; the straight-line fallback does not.
    if (next.roadGeometry && sessionId) void postRouteDrawn(sessionId, DEFAULT_MODE)
  }, [commit])

  const changeMode = useCallback(async (mode: TravelModeKey) => {
    const current = stateRef.current
    if (!current.active || !current.userCoords || !current.recommendedFacility) return
    if (current.routeLoading) return
    // Same mode with routes already shown: nothing to do. Same mode without routes: a retry.
    if (mode === current.travelMode && current.routes.length > 0) return

    const requestId = ++requestRef.current
    const startedAt = performance.now()
    commit({ ...current, routeLoading: true })

    const upFront = (await getConfig()).routes_up_front ?? 1
    if (requestId !== requestRef.current) return

    const active = stateRef.current
    if (!active.active || !active.userCoords || !active.recommendedFacility) return

    // With one route up front, route only the visible facility to save requests; otherwise route candidate batch.
    const ids = upFront <= 1
      ? [active.recommendedFacility.id]
      : candidateIds(active, upFront)

    const key = cacheKey(mode, ids)
    const cached = cacheRef.current.get(key)
    if (cached) {
      commit(applyRoutes(active, mode, cached))
      return
    }

    const response = await fetchRoutes(active.userCoords, ids, mode, active.severity)
    if (requestId !== requestRef.current) return
    if (!response) {
      // Keep the previous mode and its route on screen.
      commit({ ...stateRef.current, routeLoading: false })
      return
    }
    cacheRef.current.set(key, response)
    const next = applyRoutes(stateRef.current, mode, response)
    commit(next)

    const sessionId = sessionRef.current
    if (!sessionId || !next.roadGeometry) return
    // Measured on the next animation frame, after React has rendered and the map layer has redrawn.
    requestAnimationFrame(() => {
      void postModeChanged(sessionId, mode, performance.now() - startedAt)
      void postRouteDrawn(sessionId, mode)
    })
  }, [commit])

  const selectFacility = useCallback(async (facilityId: string) => {
    const current = stateRef.current
    if (!current.active || current.routeLoading) return
    const route = current.routes.find(r => r.facilityId === facilityId)
    // If route already in state (even with null geometry), promote immediately without network call.
    if (route) {
      commit(promoteFacility(current, facilityId))
      return
    }
    if (!current.userCoords) return
    const requestId = ++requestRef.current
    commit({ ...current, routeLoading: true })

    // Fetch routing on demand for the chosen alternative facility since it was deferred up front.
    const response = await fetchRoutes(
      current.userCoords,
      [facilityId],
      current.travelMode,
      current.severity,
    )
    if (requestId !== requestRef.current) return
    if (!response) {
      commit({ ...stateRef.current, routeLoading: false })
      return
    }
    cacheRef.current.set(cacheKey(current.travelMode, [facilityId]), response)
    commit(promoteFacility(mergeRoutes(stateRef.current, response), facilityId))
  }, [commit])

  return { triage, applyTriageResult, changeMode, selectFacility, reset }
}
