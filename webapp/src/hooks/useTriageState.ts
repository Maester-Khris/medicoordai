import { useState, useCallback } from "react"
import type { TriageUIState, TriageResult, RouteResult, FacilityCandidate } from "../../../shared/types"
import { postRouteDrawn } from "../lib/guestEvents"

const GEOAPIFY_KEY = import.meta.env.VITE_GEOAPIFY_API_KEY as string | undefined
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
}

export function useTriageState() {
  const [triage, setTriage] = useState<TriageUIState>(DEFAULT_STATE)

  const reset = useCallback(() => setTriage(DEFAULT_STATE), [])

  const applyTriageResult = useCallback(async (
    result: TriageResult,
    userCoords: { lat: number; lng: number } | null,
    sessionId?: string | null,
  ) => {
    if (!result.recommended_facility) {
      setTriage({
        ...DEFAULT_STATE,
        active: true,
        severity: result.severity,
        reasoning: result.reasoning,
        nearbyFacilities: result.nearby_facilities,
        userCoords,
        roadGeometry: null,
      })
      return
    }

    const allFacilities: FacilityCandidate[] = [
      result.recommended_facility,
      ...result.nearby_facilities,
    ]

    setTriage({
      active: true,
      severity: result.severity,
      reasoning: result.reasoning,
      recommendedFacility: result.recommended_facility,
      nearbyFacilities: result.nearby_facilities,
      userCoords,
      routes: [],
      recommendedFacilityId: result.recommended_facility.id,
      roadGeometry: null,
    })

    if (userCoords && GEOAPIFY_KEY) {
      const routes = await fetchRouteMatrix(userCoords, allFacilities)
      if (routes.length > 0) {
        const sorted = [...routes].sort((a, b) => a.etaMinutes - b.etaMinutes)
        const bestFacility = allFacilities.find(f => f.id === sorted[0].facilityId)
        let roadGeometry: [number, number][] | null = null

        if (bestFacility && userCoords) {
          roadGeometry = await fetchRoadGeometry(userCoords, bestFacility)
        }

        // Only real road geometry counts as "route drawn"; the straight-line fallback does not.
        if (roadGeometry && sessionId) void postRouteDrawn(sessionId)

        setTriage(prev => ({
          ...prev,
          routes,
          recommendedFacilityId: sorted[0].facilityId,
          roadGeometry,
        }))
      }
    }
  }, [])

  return { triage, applyTriageResult, reset }
}

async function fetchRouteMatrix(
  userCoords: { lat: number; lng: number },
  facilities: FacilityCandidate[],
): Promise<RouteResult[]> {
  if (!GEOAPIFY_KEY) {
    console.error("[RouteMatrix] VITE_GEOAPIFY_API_KEY is not set — check Doppler config and restart with doppler run -- npm run dev")
    return []
  }

  const sources = [{ location: [userCoords.lng, userCoords.lat] }]
  const targets = facilities.map(f => ({ location: [f.lng, f.lat] }))

  try {
    const resp = await fetch(
      `https://api.geoapify.com/v1/routematrix?apiKey=${GEOAPIFY_KEY}`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode: "drive", sources, targets }),
      }
    )
    if (!resp.ok) return []
    const data = await resp.json()

    return (data.sources_to_targets?.[0] ?? []).map(
      (entry: { time: number; distance: number }, idx: number) => ({
        facilityId: facilities[idx].id,
        etaMinutes: Math.round((entry.time ?? 0) / 60),
        distanceKm: Math.round((entry.distance ?? 0) / 100) / 10,
      })
    )
  } catch (err) {
    console.error("[RouteMatrix] fetch failed:", err)
    return []
  }
}
async function fetchRoadGeometry(
  from: { lat: number; lng: number },
  to: { lat: number; lng: number },
): Promise<[number, number][] | null> {
  if (!GEOAPIFY_KEY) return null
  try {
    const url =
      `https://api.geoapify.com/v1/routing` +
      `?waypoints=${from.lat},${from.lng}|${to.lat},${to.lng}` +
      `&mode=drive` +
      `&apiKey=${GEOAPIFY_KEY}`

    const resp = await fetch(url)
    if (!resp.ok) {
      console.warn("[RoadGeometry] Geoapify routing failed:", resp.status)
      return null
    }

    const data = await resp.json()
    const geom = data.features?.[0]?.geometry
    if (!geom) {
      console.warn("[RoadGeometry] no geometry in response")
      return null
    }

    // Geoapify returns MultiLineString (array of legs); LineString handled defensively.
    const rings: [number, number][][] =
      geom.type === "MultiLineString" ? geom.coordinates :
        geom.type === "LineString" ? [geom.coordinates] :
          []

    const coords: [number, number][] = rings
      .flat()
      .map(([lng, lat]: [number, number]) => [lat, lng])

    console.log("[RoadGeometry] points received:", coords.length)
    return coords.length > 0 ? coords : null
  } catch (err) {
    console.error("[RoadGeometry] fetch error:", err)
    return null
  }
}
