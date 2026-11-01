import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { DEFAULT_CONFIG, getConfig, resetConfigForTests } from "./config"

const DEMO = {
  demo_mode: true,
  starter_prompts: ["a"],
  downtown_fallback: { lat: 43.6532, lng: -79.3832 },
  modes_enabled: ["car"],
}

describe("getConfig", () => {
  beforeEach(() => resetConfigForTests())
  afterEach(() => vi.unstubAllGlobals())

  it("fetches /config once and shares the result", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => DEMO })
    vi.stubGlobal("fetch", fetchMock)
    expect(await getConfig()).toEqual(DEMO)
    expect(await getConfig()).toEqual(DEMO)
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(String(fetchMock.mock.calls[0][0])).toMatch(/\/config$/)
  })

  it("falls back to non-demo defaults when the request fails", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")))
    expect(await getConfig()).toEqual(DEFAULT_CONFIG)
    expect(DEFAULT_CONFIG.demo_mode).toBe(false)
  })

  it("falls back when the server answers with an error", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, json: async () => ({}) }))
    expect(await getConfig()).toEqual(DEFAULT_CONFIG)
  })
})
