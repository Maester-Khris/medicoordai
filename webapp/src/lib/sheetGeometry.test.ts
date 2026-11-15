import { describe, expect, it } from "vitest"
import { sheetGeometry } from "./sheetGeometry"


describe("sheetGeometry, keyboard closed", () => {
  it.each([
    // [innerHeight, free, half, full]
    [568, 448, 224, 440], // 320x568
    [640, 520, 260, 512], // 360x640
    [844, 724, 362, 716], // 390x844
    [375, 255, 176, 247], // 667x375 landscape: half has a 176 floor
  ])("height %i", (h, free, half, full) => {
    const g = sheetGeometry({ innerHeight: h, vvHeight: h, vvOffsetTop: 0 })
    expect(g).toMatchObject({ keyboardOpen: false, bottomOffset: 64, free, peek: 104, half, full })
  })

  it("keeps peek < half < full and the sheet below the 56 px top bar", () => {
    for (const h of [320, 375, 568, 640, 844, 915]) {
      const g = sheetGeometry({ innerHeight: h, vvHeight: h, vvOffsetTop: 0 })
      expect(g.peek).toBeLessThan(g.half)
      expect(g.half).toBeLessThan(g.full)
      expect(g.full + g.bottomOffset).toBeLessThanOrEqual(h - 56)
    }
  })
})

describe("sheetGeometry, on-screen keyboard", () => {
  it("iOS-shaped: layout viewport keeps its height, visual viewport shrinks", () => {
    const g = sheetGeometry({ innerHeight: 844, vvHeight: 500, vvOffsetTop: 0 })
    expect(g).toMatchObject({ keyboardOpen: true, bottomOffset: 344, free: 444, full: 436 })
  })

  it("iOS-shaped with the page scrolled (offsetTop > 0): inset excludes the offset", () => {
    const g = sheetGeometry({ innerHeight: 844, vvHeight: 500, vvOffsetTop: 40 })
    expect(g.bottomOffset).toBe(304)
    expect(g.keyboardOpen).toBe(true)
  })

  it("Android resizes-content: layout viewport shrinks, no inset, nav stays", () => {
    const g = sheetGeometry({ innerHeight: 500, vvHeight: 500, vvOffsetTop: 0 })
    expect(g).toMatchObject({ keyboardOpen: false, bottomOffset: 64, free: 380 })
  })

  it("ignores a small browser-bar resize", () => {
    const g = sheetGeometry({ innerHeight: 844, vvHeight: 790, vvOffsetTop: 0 })
    expect(g.keyboardOpen).toBe(false)
  })

  it("at 667x375 the keyboard leaves a usable full state", () => {
    const g = sheetGeometry({ innerHeight: 375, vvHeight: 190, vvOffsetTop: 0 })
    expect(g.keyboardOpen).toBe(true)
    expect(g.full).toBeGreaterThanOrEqual(g.peek)
  })
})
