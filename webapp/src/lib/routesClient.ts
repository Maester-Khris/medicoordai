import type { RoutesRequest, RoutesResponse, TravelModeKey } from "@shared/types"
import { apiFetch } from "./apiClient"

/**
 * Routes from `origin` to the candidate facilities for one travel mode. Returns null on any
 * failure (rate limit, no route, network): the map then keeps its straight-line fallback.
 */
export async function fetchRoutes(
  origin: { lat: number; lng: number },
  facilityIds: string[],
  mode: TravelModeKey,
): Promise<RoutesResponse | null> {
  if (facilityIds.length === 0) return null
  const body: RoutesRequest = { origin, facility_ids: facilityIds, mode }
  try {
    const res = await apiFetch("/routes", { method: "POST", body: JSON.stringify(body) })
    if (!res.ok) return null
    return (await res.json()) as RoutesResponse
  } catch {
    return null
  }
}
