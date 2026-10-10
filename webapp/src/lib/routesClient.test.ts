import { beforeEach, describe, expect, it, vi } from "vitest"

const apiFetch = vi.fn()
vi.mock("./apiClient", () => ({ apiFetch: (...args: unknown[]) => apiFetch(...args) }))

import { fetchRoutes } from "./routesClient"

const ORIGIN = { lat: 43.65, lng: -79.38 }
const RESPONSE = { mode: "bus", routes: [], fastest_facility_id: null }

describe("fetchRoutes", () => {
  // Block body on purpose: mockReset() returns the mock, and vitest would call a returned function
  // as a teardown after each test.
  beforeEach(() => { apiFetch.mockReset() })

  it("posts the origin, the ids and the mode, and returns the body", async () => {
    apiFetch.mockResolvedValue({ ok: true, json: async () => RESPONSE })
    expect(await fetchRoutes(ORIGIN, ["a", "b"], "bus")).toEqual(RESPONSE)
    const [path, options] = apiFetch.mock.calls[0] as [string, RequestInit]
    expect(path).toBe("/routes")
    expect(options.method).toBe("POST")
    expect(JSON.parse(String(options.body))).toEqual({ origin: ORIGIN, facility_ids: ["a", "b"], mode: "bus" })
  })

  it("returns null on an http error", async () => {
    apiFetch.mockResolvedValue({ ok: false, status: 502, json: async () => ({}) })
    expect(await fetchRoutes(ORIGIN, ["a"], "car")).toBeNull()
  })

  it("returns null when the request throws", async () => {
    apiFetch.mockRejectedValue(new Error("offline"))
    expect(await fetchRoutes(ORIGIN, ["a"], "car")).toBeNull()
  })

  it("makes no request without candidates", async () => {
    expect(await fetchRoutes(ORIGIN, [], "car")).toBeNull()
    expect(apiFetch).not.toHaveBeenCalled()
  })
})
