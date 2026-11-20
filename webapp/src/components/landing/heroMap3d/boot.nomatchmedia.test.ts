// @vitest-environment jsdom
import { describe, expect, it } from 'vitest'
import { startHeroMap } from './boot'

// The build's prerender step renders the landing page where window.matchMedia does not exist.
// The hero must start as a no-op there, not throw and empty the page.
describe('hero map without matchMedia', () => {
  it('starts as a no-op and returns a stop function', () => {
    expect(typeof window.matchMedia).not.toBe('function')
    const el = (tag: string): HTMLElement => document.createElement(tag)
    const stop = startHeroMap({
      root: el('section'),
      mapEl: el('div') as HTMLDivElement,
      fallbackEl: el('div') as HTMLDivElement,
      fallbackSvg: document.createElementNS('http://www.w3.org/2000/svg', 'svg'),
      toggleBtn: el('button') as HTMLButtonElement,
    } as Parameters<typeof startHeroMap>[0])
    expect(typeof stop).toBe('function')
    stop()
  })
})
