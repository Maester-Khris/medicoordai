import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

// Gate for the "dusk" treatment of the hero map: the light map is pulled toward the dark page
// (cooler, dimmer, vignetted at the edges) WITHOUT losing the contrast that keeps it readable and
// without changing the app's marker colours.
const read = (rel: string): string => readFileSync(fileURLToPath(new URL(rel, import.meta.url)), 'utf8')
const config = read('./config.ts')
const css = read('./HeroMap3D.css')
const component = read('./HeroMap3D.tsx')

const paletteBlock = ((): string => {
  const start = config.indexOf('PALETTE: {')
  expect(start).toBeGreaterThanOrEqual(0)
  return config.slice(start, config.indexOf('\n  },', start))
})()

const hex = (key: string): string => {
  const m = paletteBlock.match(new RegExp(`\\b${key}:\\s*'(#[0-9A-Fa-f]{6})'`))
  expect(m, `PALETTE.${key} must be a #RRGGBB string`).not.toBeNull()
  return (m as RegExpMatchArray)[1].toUpperCase()
}

const rgb = (h: string): [number, number, number] => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16)) as [number, number, number]
const lin = (c: number): number => {
  const s = c / 255
  return s <= 0.04045 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4)
}
const luminance = (h: string): number => {
  const [r, g, b] = rgb(h)
  return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)
}
const contrast = (a: string, b: string): number => {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x)
  return (hi + 0.05) / (lo + 0.05)
}
const distance = (a: string, b: string): number => {
  const [ar, ag, ab] = rgb(a)
  const [br, bg, bb] = rgb(b)
  return Math.hypot(ar - br, ag - bg, ab - bb)
}
const isCool = (h: string): boolean => {
  const [r, , b] = rgb(h)
  return b >= r // no warm (cream / yellow) cast
}

const roofColors = ((): string[] => {
  const m = paletteBlock.match(/buildingByHeight:\s*\[([^\]]*)\]/)
  expect(m).not.toBeNull()
  return ((m as RegExpMatchArray)[1].match(/#[0-9A-Fa-f]{6}/g) ?? []).map((c) => c.toUpperCase())
})()

describe('dusk palette', () => {
  it('is dimmer than the original cream map', () => {
    expect(luminance(hex('ground'))).toBeLessThan(0.74) // was 0.81
    expect(luminance(hex('ground'))).toBeGreaterThan(0.5) // still a light map, not a dark one
    expect(Math.max(...roofColors.map(luminance))).toBeLessThan(0.82) // roofs were up to 0.89
  })

  it('is cooler: no warm cast on the ground, blocks, minor roads or roofs', () => {
    for (const key of ['ground', 'blocks', 'roadMinor', 'pedestrian', 'page']) expect(isCool(hex(key)), key).toBe(true)
    expect(roofColors.length).toBeGreaterThanOrEqual(3)
    for (const roof of roofColors) expect(isCool(roof), roof).toBe(true)
  })

  it('keeps the map readable', () => {
    expect(contrast(hex('label'), hex('ground'))).toBeGreaterThanOrEqual(4.5)
    expect(contrast(hex('areaLabel'), hex('ground'))).toBeGreaterThanOrEqual(4.5)
    expect(contrast(hex('waterLabel'), hex('water'))).toBeGreaterThanOrEqual(4.5)
    expect(contrast(hex('route'), hex('ground'))).toBeGreaterThanOrEqual(3)
    // roads still separate from the ground; the major road (the Gardiner) differs by hue, so it is
    // measured by colour distance, not brightness (the original map: about 68)
    expect(contrast(hex('roadMinor'), hex('ground'))).toBeGreaterThanOrEqual(1.15)
    expect(distance(hex('roadMajor'), hex('ground'))).toBeGreaterThanOrEqual(45)
    expect(hex('roadMajor')).not.toBe(hex('roadCollector'))
  })

  it('leaves the app marker colours and the chrome untouched', () => {
    expect(hex('hospital')).toBe('#E05555')
    expect(hex('walkin')).toBe('#3AC9D4')
    expect(hex('residential')).toBe('#74C69D')
    expect(hex('chrome')).toBe('#313A3D')
    expect(hex('mint')).toBe('#47F5C0')
  })
})

describe('edge vignette', () => {
  it('draws a vignette over the map, inside the card, under the controls', () => {
    expect(component).toMatch(/className="hero-map__vignette"[^>]*aria-hidden="true"/)
    const start = css.indexOf('.hero-map__vignette {')
    expect(start).toBeGreaterThanOrEqual(0)
    const rule = css.slice(start, css.indexOf('}', start))
    expect(rule).toContain('radial-gradient')
    expect(rule).toContain('pointer-events: none')
    expect(rule).toMatch(/z-index:\s*1\s*;/) // MapLibre's control container (attribution) is z-index 2
  })

  it('is not the old fade into the page', () => {
    expect(css).not.toContain('hero-map__fade')
    expect(css).not.toContain('--hm-page')
  })
})
