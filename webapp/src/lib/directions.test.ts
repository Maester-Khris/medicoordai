import { describe, expect, it, vi } from "vitest"
import { buildDirectionsUrl, openDirections, DIRECTIONS_UNAVAILABLE } from "./directions"

describe("buildDirectionsUrl", () => {
  it("builds the universal Google Maps directions URL", () => {
    expect(buildDirectionsUrl(43.6629, -79.3957)).toBe(
      "https://www.google.com/maps/dir/?api=1&destination=43.6629%2C-79.3957")
  })

  it("returns null when a coordinate is not a finite number", () => {
    expect(buildDirectionsUrl(NaN, -79)).toBeNull()
    expect(buildDirectionsUrl(43, Infinity)).toBeNull()
    expect(buildDirectionsUrl(undefined as unknown as number, 1)).toBeNull()
  })

  it("returns null for out-of-range coordinates", () => {
    expect(buildDirectionsUrl(91, 0)).toBeNull()
    expect(buildDirectionsUrl(0, -181)).toBeNull()
  })
})

describe("openDirections", () => {
  it("opens a new tab without opener access and reports success", () => {
    const open = vi.fn()
    expect(openDirections(43.6, -79.4, open)).toBe(true)
    expect(open).toHaveBeenCalledWith(
      "https://www.google.com/maps/dir/?api=1&destination=43.6%2C-79.4", "_blank", "noopener,noreferrer")
  })

  it("does nothing and reports failure without usable coordinates", () => {
    const open = vi.fn()
    expect(openDirections(NaN, 0, open)).toBe(false)
    expect(open).not.toHaveBeenCalled()
  })

  it("has the unavailable message", () => {
    expect(DIRECTIONS_UNAVAILABLE).toBe("Directions are not available for this place.")
  })
})
