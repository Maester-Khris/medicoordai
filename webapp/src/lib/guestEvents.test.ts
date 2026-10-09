import { beforeEach, describe, expect, it, vi } from "vitest"

const apiFetch = vi.fn()
const getConfig = vi.fn()
vi.mock("./apiClient", () => ({ apiFetch: (...args: unknown[]) => apiFetch(...args) }))
vi.mock("./config", () => ({ getConfig: () => getConfig() }))

import { postModeChanged, postRouteDrawn } from "./guestEvents"

const sent = () => apiFetch.mock.calls.map(call => JSON.parse(String((call[1] as RequestInit).body)))

describe("guest events", () => {
  beforeEach(() => {
    apiFetch.mockReset().mockResolvedValue({ ok: true })
    getConfig.mockReset().mockResolvedValue({ demo_mode: true })
  })

  it("sends route_drawn with its mode once per session", async () => {
    await postRouteDrawn("s-once", "bike")
    await postRouteDrawn("s-once", "walk")
    expect(sent()).toEqual([{ type: "route_drawn", session_id: "s-once", mode: "bike" }])
  })

  it("sends mode_changed every time, with a whole number of milliseconds", async () => {
    await postModeChanged("s-mode", "bus", 812.6)
    await postModeChanged("s-mode", "walk", 40)
    expect(sent()).toEqual([
      { type: "mode_changed", session_id: "s-mode", mode: "bus", duration_ms: 813 },
      { type: "mode_changed", session_id: "s-mode", mode: "walk", duration_ms: 40 },
    ])
  })

  it("clamps the duration to the range the api accepts", async () => {
    await postModeChanged("s-clamp", "car", 999999)
    await postModeChanged("s-clamp", "car", -5)
    expect(sent().map(e => e.duration_ms)).toEqual([120000, 0])
  })

  it("sends nothing outside demo mode", async () => {
    getConfig.mockResolvedValue({ demo_mode: false })
    await postRouteDrawn("s-off", "car")
    await postModeChanged("s-off", "car", 10)
    expect(apiFetch).not.toHaveBeenCalled()
  })

  it("never throws when the request fails", async () => {
    apiFetch.mockRejectedValue(new Error("offline"))
    await expect(postRouteDrawn("s-fail", "car")).resolves.toBeUndefined()
    await expect(postModeChanged("s-fail", "car", 10)).resolves.toBeUndefined()
  })
})
