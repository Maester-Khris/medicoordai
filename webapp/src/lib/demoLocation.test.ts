import { afterEach, describe, expect, it, vi } from "vitest"
import type { AppConfig } from "@shared/types"
import { DEMO_LOCATION_WAIT_MS, isInToronto, requestLocation, resolveDemoCoords } from "./demoLocation"

const DOWNTOWN = { lat: 43.6532, lng: -79.3832 }
const demo: AppConfig = { demo_mode: true, starter_prompts: [], downtown_fallback: DOWNTOWN, modes_enabled: ["car"] }
const normal: AppConfig = { ...demo, demo_mode: false }

describe("isInToronto", () => {
  it("accepts points inside the box and rejects points outside", () => {
    expect(isInToronto({ lat: 43.70, lng: -79.40 })).toBe(true)
    expect(isInToronto({ lat: 45.50, lng: -73.57 })).toBe(false)  // Montreal
    expect(isInToronto({ lat: 43.70, lng: 79.40 })).toBe(false)   // wrong sign
  })

  it("treats the box edges as inside", () => {
    expect(isInToronto({ lat: 43.58, lng: -79.64 })).toBe(true)
    expect(isInToronto({ lat: 43.86, lng: -79.12 })).toBe(true)
    expect(isInToronto({ lat: 43.8601, lng: -79.12 })).toBe(false)
  })
})

describe("resolveDemoCoords", () => {
  it("keeps a Toronto position", () => {
    const here = { lat: 43.70, lng: -79.40 }
    expect(resolveDemoCoords(here, demo)).toEqual({ coords: here, usedFallback: false })
  })

  it("uses downtown when there is no position", () => {
    expect(resolveDemoCoords(null, demo)).toEqual({ coords: DOWNTOWN, usedFallback: true })
  })

  it("uses downtown when the position is outside Toronto", () => {
    expect(resolveDemoCoords({ lat: 45.50, lng: -73.57 }, demo)).toEqual({ coords: DOWNTOWN, usedFallback: true })
  })

  it("never substitutes a location outside demo mode", () => {
    expect(resolveDemoCoords(null, normal)).toEqual({ coords: null, usedFallback: false })
    const away = { lat: 45.50, lng: -73.57 }
    expect(resolveDemoCoords(away, normal)).toEqual({ coords: away, usedFallback: false })
  })
})

describe("requestLocation", () => {
  afterEach(() => vi.useRealTimers())

  const never = () => new Promise<null>(() => {})

  it("gives up after the demo wait when the prompt is ignored", async () => {
    vi.useFakeTimers()
    const pending = requestLocation(never, demo)
    await vi.advanceTimersByTimeAsync(DEMO_LOCATION_WAIT_MS)
    expect(await pending).toBeNull()
  })

  it("returns the position when it arrives in time", async () => {
    const here = { lat: 43.70, lng: -79.40 }
    expect(await requestLocation(async () => here, demo)).toEqual(here)
  })

  it("does not cut the wait short outside demo mode", async () => {
    vi.useFakeTimers()
    let settled = false
    void requestLocation(never, normal).then(() => { settled = true })
    await vi.advanceTimersByTimeAsync(DEMO_LOCATION_WAIT_MS * 4)
    expect(settled).toBe(false)
  })
})
