import type { GuestEventRequest } from "@shared/types"
import { apiFetch } from "./apiClient"
import { getConfig } from "./config"

const sentForSession = new Set<string>()

/** Tells the backend a real road route was drawn. Sent at most once per session; never throws. */
export async function postRouteDrawn(sessionId: string): Promise<void> {
  const config = await getConfig()
  if (!config.demo_mode || sentForSession.has(sessionId)) return
  sentForSession.add(sessionId)
  const body: GuestEventRequest = { type: "route_drawn", session_id: sessionId }
  try {
    await apiFetch("/events", { method: "POST", body: JSON.stringify(body) })
  } catch {
    // the event is a measurement, not a feature: a failure must not disturb the user
  }
}
