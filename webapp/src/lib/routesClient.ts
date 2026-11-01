import type { RoutesRequest, RoutesResponse, Severity, TravelModeKey } from "@shared/types"
import { apiFetch } from "./apiClient"

/**
 * Routes from `origin` to the candidate facilities for one travel mode. Returns null on any
 * failure (rate limit, no route, network): the map then keeps its straight-line fallback.
 * Passes `severity` when provided so the backend can bypass provider rate limits for urgent/emergent cases.
 */
export async function fetchRoutes(
  origin: { lat: number; lng: number },
  facilityIds: string[],
  mode: TravelModeKey,
  severity?: Severity | null,
): Promise<RoutesResponse | null> {
  if (facilityIds.length === 0) return null
  const body: RoutesRequest = { origin, facility_ids: facilityIds, mode }
  if (severity) body.severity = severity
  try {
    const res = await apiFetch("/routes", { method: "POST", body: JSON.stringify(body) })
    if (!res.ok) return null
    return (await res.json()) as RoutesResponse
  } catch {
    return null
  }
}

