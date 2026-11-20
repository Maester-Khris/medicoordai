// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { act } from "react"
import { createRoot, type Root } from "react-dom/client"
import type { Facility } from "@shared/types"
import { FacilityList, PAGE_SIZE } from "./FacilityList"

;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true

let trigger: (() => void) | null = null
class FakeObserver {
  constructor(cb: IntersectionObserverCallback) {
    trigger = () => cb([{ isIntersecting: true } as IntersectionObserverEntry], this as unknown as IntersectionObserver)
  }
  observe() {}
  disconnect() {}
  unobserve() {}
}

const ORIGIN = { lat: 43.65, lng: -79.38 }
function make(n: number): Facility[] {
  return Array.from({ length: n }, (_, i) => ({
    id: `f${i}`, name: `Facility ${i}`, category: "hospital", source_facility_type: "x",
    accepted_severity: ["urgent"], address: "1 Main St",
    lat: 43.65 + i * 0.001, lng: -79.38, // f0 is the nearest
    wait_minutes: i === 0 ? 35 : null,
  }))
}

let root: Root
let host: HTMLDivElement
const onShowOnMap = vi.fn()
const onDirections = vi.fn(() => true)

function mount(facilities: Facility[], loading = false, usedFallback = false) {
  act(() => root.render(
    <FacilityList facilities={facilities} loading={loading} origin={ORIGIN} originIsFallback={usedFallback}
      onShowOnMap={onShowOnMap} onDirections={onDirections} />))
}
const rows = () => host.querySelectorAll("[data-testid=facility-row]")

beforeEach(() => {
  trigger = null
  vi.stubGlobal("IntersectionObserver", FakeObserver)
  host = document.createElement("div")
  root = createRoot(host)
  onShowOnMap.mockClear(); onDirections.mockClear()
})
afterEach(() => { act(() => root.unmount()); vi.unstubAllGlobals() })

describe("FacilityList", () => {
  it("renders the nearest 8 first, sorted by distance", () => {
    mount(make(20).reverse())
    expect(rows()).toHaveLength(PAGE_SIZE)
    expect(rows()[0].textContent).toContain("Facility 0")
    expect(rows()[1].textContent).toContain("Facility 1")
  })

  it("loads 8 more when the sentinel comes into view, and stops at the end", () => {
    mount(make(20))
    act(() => trigger!())
    expect(rows()).toHaveLength(16)
    act(() => trigger!())
    expect(rows()).toHaveLength(20)
    expect(host.querySelector("[data-testid=facility-sentinel]")).toBeNull()
  })

  it("shows distance, and the wait only when present", () => {
    mount(make(3))
    expect(rows()[0].textContent).toMatch(/\d\.\d km/)
    expect(rows()[0].textContent).toContain("~35 min wait")
    expect(rows()[1].textContent).not.toContain("wait")
  })

  it("says where the distances are measured from when the fallback is used", () => {
    mount(make(2), false, true)
    expect(host.textContent).toContain("Distances from downtown Toronto")
  })

  it("has loading and empty states", () => {
    mount([], true)
    expect(host.textContent).toContain("Loading facilities")
    mount([], false)
    expect(host.textContent).toContain("No facilities found")
  })

  it("expands a row to Directions and Show on map, and calls the handlers", () => {
    mount(make(3))
    expect(host.querySelector("[data-testid=facility-directions]")).toBeNull()
    act(() => (rows()[1].querySelector("button") as HTMLButtonElement).click())
    act(() => (host.querySelector("[data-testid=facility-directions]") as HTMLButtonElement).click())
    const [name, lat, lng] = onDirections.mock.calls[0] as unknown as [string, number, number]
    expect(name).toBe("Facility 1")
    expect(lat).toBeCloseTo(43.651, 6)
    expect(lng).toBe(-79.38)
    act(() => (host.querySelector("[data-testid=facility-show-on-map]") as HTMLButtonElement).click())
    expect(onShowOnMap).toHaveBeenCalledWith("f1")
  })

  it("shows a message when directions are unavailable", () => {
    onDirections.mockReturnValueOnce(false)
    mount(make(1))
    act(() => (rows()[0].querySelector("button") as HTMLButtonElement).click())
    act(() => (host.querySelector("[data-testid=facility-directions]") as HTMLButtonElement).click())
    expect(host.textContent).toContain("Directions are not available for this place.")
  })
})
