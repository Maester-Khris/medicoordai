import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

// Gate for the "product-preview card" framing of the hero map: a light panel on the dark page must
// have a crisp, deliberate edge, not a fade into the page.
const read = (rel: string): string => readFileSync(fileURLToPath(new URL(rel, import.meta.url)), 'utf8')

const css = read('./HeroMap3D.css')
const component = read('./HeroMap3D.tsx')
const boot = read('./boot.ts')
const landing = read('../../../pages/LandingPage.tsx')

// the declarations inside the first `.hero-map { ... }` rule
const heroMapRule = (): string => {
  const start = css.indexOf('.hero-map {')
  expect(start).toBeGreaterThanOrEqual(0)
  return css.slice(start, css.indexOf('}', start))
}

describe('hero map card framing', () => {
  it('no longer fades the panel into the page', () => {
    expect(component).not.toContain('hero-map__fade')
    expect(css).not.toContain('hero-map__fade')
    expect(boot).not.toContain('--hm-page')
    expect(css).not.toContain('--hm-page')
  })

  it('does not take a page colour any more', () => {
    expect(component).not.toContain('pageColor')
    expect(boot).not.toContain('pageColor')
    expect(landing).not.toContain('pageColor')
  })

  it('gives the panel a thin border and a soft glow', () => {
    const rule = heroMapRule()
    expect(rule).toMatch(/border:\s*1px solid/)
    expect(rule).toMatch(/box-shadow:/)
    expect(rule).toMatch(/border-radius:/)
  })

  it('does not clip the glow with an overflow-hidden wrapper in the landing page', () => {
    const at = landing.indexOf('<HeroMap3D')
    expect(at).toBeGreaterThan(0)
    // the opening tag of the wrapper that holds the map
    const wrapper = landing.slice(landing.lastIndexOf('<div', at), at)
    expect(wrapper).not.toContain('overflow-hidden')
  })

  it('keeps what the card needs to stay usable', () => {
    expect(component).toContain('hero-map__toggle') // pause / play
    expect(css).toContain('.hero-map__haze') // top haze stays inside the map
    expect(css).toContain('overflow: hidden') // the map still clips to its own rounded corners
  })
})
