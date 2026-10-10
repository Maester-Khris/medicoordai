import type { GuestEventRequest, TravelModeKey } from "@shared/types"
import { apiFetch } from "./apiClient"
import { getConfig } from "./config"

const MAX_DURATION_MS = 120000
const sentForSession = new Set<string>()

async function send(body: GuestEventRequest): Promise<void> {
  try {
    await apiFetch("/events", { method: "POST", body: JSON.stringify(body) })
  } catch {
    // the event is a measurement, not a feature: a failure must not disturb the user
  }
}

/** Tells the backend a real road route was drawn. Sent at most once per session; never throws. */
export async function postRouteDrawn(sessionId: string, mode: TravelModeKey): Promise<void> {
  const config = await getConfig()
  if (!config.demo_mode || sentForSession.has(sessionId)) return
  sentForSession.add(sessionId)
  await send({ type: "route_drawn", session_id: sessionId, mode })
}

/** How long a travel-mode change took, from the click to the redraw. Never throws. */
export async function postModeChanged(
  sessionId: string,
  mode: TravelModeKey,
  durationMs: number,
): Promise<void> {
  const config = await getConfig()
  if (!config.demo_mode) return
  const duration_ms = Math.min(MAX_DURATION_MS, Math.max(0, Math.round(durationMs)))
  await send({ type: "mode_changed", session_id: sessionId, mode, duration_ms })
}
