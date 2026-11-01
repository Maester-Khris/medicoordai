import { describe, expect, it } from "vitest"
import type { FacilityCandidate, RoutesResponse, TriageUIState } from "@shared/types"
import { applyRoutes, candidateIds, mergeRoutes, promoteFacility, toRouteResults } from "./triageRoutes"

const facility = (id: string): FacilityCandidate => ({
  id, name: `Facility ${id}`, category: "hospital", address: "1 Main St", lat: 43.6, lng: -79.4, distanceKm: 1,
})

const A = facility("a")
const B = facility("b")
const C = facility("c")
const LINE_A: [number, number][] = [[43.65, -79.38], [43.6, -79.4]]
const LINE_B: [number, number][] = [[43.65, -79.38], [43.7, -79.3]]

const BASE: TriageUIState = {
  active: true,
  severity: "urgent",
  reasoning: "because",
  recommendedFacility: A,
  nearbyFacilities: [B, C],
  userCoords: { lat: 43.65, lng: -79.38 },
  routes: [],
  recommendedFacilityId: "a",
  roadGeometry: null,
  travelMode: "car",
  routeLoading: true,
}

const RESPONSE: RoutesResponse = {
  mode: "bike",
  routes: [
    { facility_id: "a", eta_minutes: 20, distance_km: 5.1, geometry: LINE_A },
    { facility_id: "b", eta_minutes: 9, distance_km: 2.4, geometry: LINE_B },
    { facility_id: "c", eta_minutes: null, distance_km: null, geometry: null },
  ],
  fastest_facility_id: "b",
}

describe("candidateIds", () => {
  it("lists the recommended facility first, then the others", () => {
    expect(candidateIds(BASE)).toEqual(["a", "b", "c"])
  })

  it("keeps only the first ones when a number up front is given", () => {
    expect(candidateIds(BASE, 1)).toEqual(["a"])
    expect(candidateIds(BASE, 2)).toEqual(["a", "b"])
    expect(candidateIds(BASE, 3)).toEqual(["a", "b", "c"])
  })

  it("is empty without a recommendation", () => {
    expect(candidateIds({ ...BASE, recommendedFacility: null, nearbyFacilities: [] })).toEqual([])
  })
})

describe("toRouteResults", () => {
  it("keeps only candidates that have a route", () => {
    expect(toRouteResults(RESPONSE)).toEqual([
      { facilityId: "a", etaMinutes: 20, distanceKm: 5.1, geometry: LINE_A },
      { facilityId: "b", etaMinutes: 9, distanceKm: 2.4, geometry: LINE_B },
    ])
  })

  it("carries the estimated flag of a route that was not drawn", () => {
    const estimated: RoutesResponse = {
      mode: "car",
      routes: [{ facility_id: "a", eta_minutes: 7, distance_km: 2.1, geometry: null, estimated: true }],
      fastest_facility_id: "a",
    }
    expect(toRouteResults(estimated)).toEqual([
      { facilityId: "a", etaMinutes: 7, distanceKm: 2.1, geometry: null, estimated: true },
    ])
  })
})

describe("applyRoutes", () => {
  it("stores the routes, the mode, and moves the recommendation to the fastest candidate", () => {
    const next = applyRoutes(BASE, "bike", RESPONSE)
    expect(next.travelMode).toBe("bike")
    expect(next.routeLoading).toBe(false)
    expect(next.routes).toHaveLength(2)
    expect(next.recommendedFacilityId).toBe("b")
    expect(next.recommendedFacility).toEqual(B)
    expect(next.nearbyFacilities).toEqual([A, C])
    expect(next.roadGeometry).toEqual(LINE_B)
  })

  it("clears the road geometry when no candidate could be routed", () => {
    const none: RoutesResponse = { ...RESPONSE, routes: [], fastest_facility_id: null }
    const next = applyRoutes({ ...BASE, roadGeometry: LINE_A }, "walk", none)
    expect(next.roadGeometry).toBeNull()
    expect(next.recommendedFacilityId).toBe("a")
    expect(next.routes).toEqual([])
  })

  it("does not mutate the state it is given", () => {
    const frozen = Object.freeze({ ...BASE })
    expect(() => applyRoutes(frozen, "bike", RESPONSE)).not.toThrow()
    expect(frozen.recommendedFacilityId).toBe("a")
  })
})

describe("promoteFacility", () => {
  const routed = applyRoutes(BASE, "bike", RESPONSE)

  it("swaps the recommendation and its geometry without touching the routes", () => {
    const next = promoteFacility(routed, "a")
    expect(next.recommendedFacility).toEqual(A)
    expect(next.nearbyFacilities).toEqual([B, C])
    expect(next.roadGeometry).toEqual(LINE_A)
    expect(next.routes).toBe(routed.routes)
  })

  it("returns the same state for an unknown facility", () => {
    expect(promoteFacility(routed, "zzz")).toBe(routed)
  })

  it("promotes a candidate that has no route with a null geometry", () => {
    expect(promoteFacility(routed, "c").roadGeometry).toBeNull()
  })
})

describe("mergeRoutes", () => {
  const onlyA: RoutesResponse = {
    mode: "bike",
    routes: [{ facility_id: "a", eta_minutes: 20, distance_km: 5.1, geometry: LINE_A }],
    fastest_facility_id: "a",
  }
  const onlyB: RoutesResponse = {
    mode: "bike",
    routes: [{ facility_id: "b", eta_minutes: 9, distance_km: 2.4, geometry: LINE_B }],
    fastest_facility_id: "b",
  }
  const shown = applyRoutes(BASE, "bike", onlyA)

  it("adds the new route and keeps the ones already there", () => {
    const next = mergeRoutes({ ...shown, routeLoading: true }, onlyB)
    expect(next.routes.map(r => r.facilityId)).toEqual(["a", "b"])
    expect(next.routeLoading).toBe(false)
  })

  it("does not move the recommendation", () => {
    const next = mergeRoutes(shown, onlyB)
    expect(next.recommendedFacilityId).toBe("a")
    expect(next.roadGeometry).toEqual(LINE_A)
  })

  it("replaces a route for the same facility", () => {
    const faster: RoutesResponse = {
      ...onlyA, routes: [{ facility_id: "a", eta_minutes: 12, distance_km: 5.1, geometry: LINE_A }],
    }
    expect(mergeRoutes(shown, faster).routes).toEqual([
      { facilityId: "a", etaMinutes: 12, distanceKm: 5.1, geometry: LINE_A },
    ])
  })

  it("lets the merged route be promoted", () => {
    const next = promoteFacility(mergeRoutes(shown, onlyB), "b")
    expect(next.recommendedFacilityId).toBe("b")
    expect(next.roadGeometry).toEqual(LINE_B)
    expect(next.nearbyFacilities).toEqual([A, C])
  })
})
