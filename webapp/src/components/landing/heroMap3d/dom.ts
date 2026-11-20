import { CHIP, USER, type Facility, type FacilityKind } from './config'

export function el<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  className?: string,
  text?: string,
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag)
  if (className) node.className = className
  if (text != null) node.textContent = text
  return node
}

// The app's round badges: a coloured disc, a white ring, a white icon. Three different icons so the
// facility types never rely on colour alone (each pin also has a text label).
const PIN_GLYPHS: Record<FacilityKind, string> = {
  hospital: '<path d="M10.2 6h3.6v4.2H18v3.6h-4.2V18h-3.6v-4.2H6v-3.6h4.2z" fill="#fff"/>',
  walkin:
    '<polyline points="4.5,12.6 8.4,12.6 10.2,7.4 13.4,17 15.2,12.6 19.5,12.6" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>',
  residential: '<path d="M12 5.6 5.2 11.4h1.9v6.4h3.5v-4h2.8v4h3.5v-6.4h1.9z" fill="#fff"/>',
}

const pinSvg = (kind: FacilityKind): string =>
  `<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="10.6" fill="currentColor" stroke="#fff" stroke-width="1.8"/>${PIN_GLYPHS[kind]}</svg>`

export function pinElement(f: Facility, withLabel = true): HTMLDivElement {
  const pin = el('div', `hm-pin hm-pin--${f.kind}${f.dest ? ' hm-pin--dest' : ''}`)
  pin.innerHTML = pinSvg(f.kind)
  if (withLabel) pin.append(el('span', 'hm-label', f.label))
  return pin
}

export function userElement(withLabel = true): HTMLDivElement {
  const node = el('div', 'hm-user')
  node.append(el('span', 'hm-user__pulse'), el('span', 'hm-user__dot'))
  if (withLabel) node.append(el('span', 'hm-label', USER.label))
  return node
}

export function chipElement(): HTMLDivElement {
  const chip = el('div', 'hm-chip')
  const inner = el('div', 'hm-chip__inner')
  inner.append(
    el('p', 'hm-chip__name', CHIP.name),
    el('p', 'hm-chip__type', CHIP.reason),
    el('p', 'hm-chip__meta', `${CHIP.distance} · ${CHIP.wait}`),
  )
  // visible "sample" tag; the visually hidden part spells it out for screen readers
  const sample = el('span', 'hm-chip__sample', 'sample')
  sample.append(el('span', 'hm-sr-only', ' values, not live data'))
  chip.append(inner, sample)
  return chip
}
