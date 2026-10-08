import type { AppConfig } from "@shared/types"

const BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000"

/** What the app does when /config cannot be reached: today's non-demo behaviour. */
export const DEFAULT_CONFIG: AppConfig = {
  demo_mode: false,
  starter_prompts: [],
  downtown_fallback: { lat: 43.6532, lng: -79.3832 },
  modes_enabled: ["car", "bike", "bus", "walk"],
}

let pending: Promise<AppConfig> | null = null

export function getConfig(): Promise<AppConfig> {
  pending ??= fetch(`${BASE_URL}/config`)
    .then(res => (res.ok ? (res.json() as Promise<AppConfig>) : DEFAULT_CONFIG))
    .catch(() => DEFAULT_CONFIG)
  return pending
}

export function resetConfigForTests(): void {
  pending = null
}
