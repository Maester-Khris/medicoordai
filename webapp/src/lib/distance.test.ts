import { describe, expect, it } from "vitest"
import { haversineKm, sortByDistance } from "./distance"

const CN_TOWER = { lat: 43.6426, lng: -79.3871 }
const UOFT = { lat: 43.6629, lng: -79.3957 }

describe("haversineKm", () => {
  it("is 0 for the same point", () => {
    expect(haversineKm(CN_TOWER, CN_TOWER)).toBe(0)
  })
  it("matches a known Toronto pair (about 2.3 km)", () => {
    expect(haversineKm(CN_TOWER, UOFT)).toBeGreaterThan(2.2)
    expect(haversineKm(CN_TOWER, UOFT)).toBeLessThan(2.4)
  })
})

describe("sortByDistance", () => {
  const near = { name: "near", ...UOFT }
  const far = { name: "far", lat: 43.9, lng: -79.0 }
  const broken = { name: "broken", lat: NaN, lng: 0 }

  it("sorts nearest first and attaches the distance", () => {
    const out = sortByDistance([far, near], CN_TOWER)
    expect(out.map(r => r.item.name)).toEqual(["near", "far"])
    expect(out[0].km).toBeLessThan(out[1].km)
  })
  it("puts items without usable coordinates last instead of dropping them", () => {
    expect(sortByDistance([broken, far, near], CN_TOWER).map(r => r.item.name)).toEqual(["near", "far", "broken"])
  })
  it("does not mutate its input", () => {
    const input = [far, near]
    sortByDistance(input, CN_TOWER)
    expect(input[0]).toBe(far)
  })
})
