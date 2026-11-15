// Stub backend for the mobile and emergency end-to-end tests. Every API call is answered here,
// so no LLM, database or routing service is needed and every result state can be produced.
import type { Page, Route } from "@playwright/test"

export type ScenarioName =
  | "routine" | "emergent" | "emergent_nofac" | "capped" | "capped_noresult"
  | "no_provider" | "followup" | "http500" | "netabort"

interface Candidate { id: string; name: string; category: string; address: string; lat: number; lng: number; distanceKm: number }
interface Scenario {
  reply?: string
  status?: number
  abort?: boolean
  triage?: { severity: string; reasoning: string; recommended_facility: Candidate | null; nearby_facilities: Candidate[] } | null
}

const FACILITY_ROWS: [string, string, string, string, number, number][] = [
  ["f-tgh", "Toronto General Hospital", "hospital", "200 Elizabeth St, Toronto, ON", 43.6591, -79.3877],
  ["f-msh", "Mount Sinai Hospital", "hospital", "600 University Ave, Toronto, ON", 43.6576, -79.3904],
  ["f-smh", "St. Michael's Hospital", "hospital", "36 Queen St E, Toronto, ON", 43.6534, -79.3775],
  ["f-twh", "Toronto Western Hospital", "hospital", "399 Bathurst St, Toronto, ON", 43.6534, -79.4058],
  ["f-sbk", "Sunnybrook Health Sciences Centre", "hospital", "2075 Bayview Ave, Toronto, ON", 43.7225, -79.3755],
  ["f-sjh", "St. Joseph's Health Centre", "hospital", "30 The Queensway, Toronto, ON", 43.6403, -79.4502],
  ["f-ann", "Annex Walk-In Medical Clinic", "ambulatory", "360 Bloor St W, Toronto, ON", 43.6667, -79.404],
  ["f-cpl", "College Park Walk-In Clinic", "ambulatory", "444 Yonge St, Toronto, ON", 43.6597, -79.383],
  ["f-qwc", "Queen West Urgent Care Clinic", "ambulatory", "561 Queen St W, Toronto, ON", 43.6479, -79.4006],
  ["f-dfc", "Danforth Family Medical Centre", "ambulatory", "1 Danforth Ave, Toronto, ON", 43.6765, -79.358],
  ["f-ltc", "Kensington Gardens Residence", "residential", "45 Brunswick Ave, Toronto, ON", 43.6566, -79.4066],
]

export const FACILITIES = FACILITY_ROWS.map(([id, name, category, address, lat, lng], i) => ({
  id, name, category, source_facility_type: "x",
  accepted_severity: ["routine", "moderate", "urgent", "emergent"],
  address, lat, lng, phone: null, business_status: "OPERATIONAL",
  weekday_hours: ["Monday: Open 24 hours"], wait_minutes: 20 + i * 7, raw_wait: null, predicted: false,
}))

const cand = (id: string, km: number): Candidate => {
  const f = FACILITIES.find(x => x.id === id)!
  return { id, name: f.name, category: f.category, address: f.address, lat: f.lat, lng: f.lng, distanceKm: km }
}

export const CONFIG = {
  demo_mode: true,
  starter_prompts: ["I have a fever and a sore throat", "Chest pain and shortness of breath"],
  downtown_fallback: { lat: 43.6532, lng: -79.3832 },
  modes_enabled: ["car", "bike", "bus", "walk"],
  routes_up_front: 1,
}

const SAFETY_LINE = "If this is an emergency, call 911. For other health help, call 211."
const CAPPED_NOTE = "I'm wrapping up here to keep this conversation short, so this is based on what you've shared so far. If your symptoms change or get worse, call 911."

export const EMERGENT_REPLY = "Chest pain with shortness of breath can be serious. Toronto General Hospital at 200 Elizabeth St is about 0.8 km away. Please call 911 now."

const SCENARIOS: Record<ScenarioName, Scenario> = {
  routine: { reply: `This sounds routine. College Park Walk-In Clinic is about 0.9 km away. ${SAFETY_LINE}`,
    triage: { severity: "routine", reasoning: "Mild.", recommended_facility: cand("f-cpl", 0.9), nearby_facilities: [cand("f-ann", 1.1)] } },
  emergent: { reply: EMERGENT_REPLY,
    triage: { severity: "emergent", reasoning: "Chest pain.", recommended_facility: cand("f-tgh", 0.8), nearby_facilities: [cand("f-msh", 0.7)] } },
  emergent_nofac: { reply: "Chest pain with shortness of breath can be serious. I cannot point to a facility from here. Please call 911 now.",
    triage: { severity: "emergent", reasoning: "Chest pain.", recommended_facility: null, nearby_facilities: [] } },
  capped: { reply: `Based on what you've told me, this looks emergent. Please call 911 now. ${CAPPED_NOTE}`,
    triage: { severity: "emergent", reasoning: "Chest pain.", recommended_facility: cand("f-tgh", 0.8), nearby_facilities: [] } },
  capped_noresult: { reply: `I couldn't finish assessing this. ${SAFETY_LINE}`, triage: null },
  no_provider: { reply: `I'm having trouble processing your request right now. ${SAFETY_LINE}`, triage: null },
  followup: { reply: "How long have you had the chest pain, and is it constant?", triage: null },
  http500: { status: 500 },
  netabort: { abort: true },
}

const now = () => new Date().toISOString()
let counter = 0

/** Answers every API call for this page. `scenario` can be changed between turns via the returned setter. */
export async function stubBackend(page: Page, initial: ScenarioName): Promise<{ setScenario: (s: ScenarioName) => void }> {
  let current = initial
  const json = (route: Route, status: number, body: unknown, headers: Record<string, string> = {}) =>
    route.fulfill({ status, contentType: "application/json", headers: { "access-control-allow-origin": "*", "access-control-expose-headers": "ETag, X-Wait-As-Of", ...headers }, body: JSON.stringify(body) })

  await page.route(/\/(config|facilities|chat\/sessions|chat\/message|routes|feedback|events)(\?.*)?$/, async route => {
    const req = route.request()
    const url = new URL(req.url())
    if (!["localhost:8000", "127.0.0.1:8000"].includes(url.host)) return route.fallback()
    const p = url.pathname
    if (req.method() === "OPTIONS") return route.fulfill({ status: 204, headers: { "access-control-allow-origin": "*", "access-control-allow-headers": "*", "access-control-allow-methods": "*" } })
    if (p === "/config") return json(route, 200, CONFIG)
    if (p === "/facilities") return json(route, 200, FACILITIES, { ETag: '"e2e"', "X-Wait-As-Of": now() })
    if (p === "/chat/sessions" && req.method() === "POST") return json(route, 200, { id: `sess-${++counter}`, user_id: "guest", title: "e2e", created_at: now(), updated_at: now() })
    if (p === "/chat/sessions") return json(route, 200, { sessions: [], messages: {} })
    if (p === "/chat/message") {
      const sc = SCENARIOS[current]
      if (sc.abort) return route.abort("failed")
      if (sc.status) return json(route, sc.status, { detail: "stubbed failure" })
      const body = req.postDataJSON() as { session_id?: string; content?: string }
      const sid = body.session_id ?? "sess"
      return json(route, 200, {
        user_message: { id: `u-${++counter}`, session_id: sid, user_id: "guest", role: "user", content: body.content ?? "", created_at: now() },
        assistant_message: { id: `a-${++counter}`, session_id: sid, user_id: "guest", role: "assistant", content: sc.reply, created_at: now() },
        triage: sc.triage ?? null,
      })
    }
    if (p === "/routes") {
      const body = req.postDataJSON() as { facility_ids?: string[]; mode?: string; origin?: { lat: number; lng: number } }
      const o = body.origin ?? { lat: 43.66, lng: -79.39 }
      const routes = (body.facility_ids ?? []).map((fid, i) => {
        const f = FACILITIES.find(x => x.id === fid) ?? FACILITIES[0]
        const geometry = Array.from({ length: 9 }, (_, k) => [o.lat + ((f.lat - o.lat) * k) / 8, o.lng + ((f.lng - o.lng) * k) / 8])
        return { facility_id: fid, eta_minutes: 6 + i * 3, distance_km: 1.2 + i * 0.5, geometry }
      })
      return json(route, 200, { mode: body.mode ?? "car", routes, fastest_facility_id: body.facility_ids?.[0] ?? null })
    }
    return route.fulfill({ status: 204, headers: { "access-control-allow-origin": "*" } })
  })

  // Nothing else leaves the machine: map tiles and fonts are allowed, analytics and push are not.
  await page.route(/^https:\/\/([^/]*\.)?(onesignal\.com|googletagmanager\.com|supabase\.co)\//, route => route.abort())
  return { setScenario: s => { current = s } }
}
