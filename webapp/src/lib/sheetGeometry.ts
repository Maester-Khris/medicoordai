export const TOP_BAR_H = 56
export const BOTTOM_NAV_H = 64
const PEEK_H = 104 // handle strip with notice (44) + input row (52) + padding
const KEYBOARD_MIN_INSET = 100 // smaller visual-viewport shrinks are browser bars, not a keyboard

export interface ViewportInput {
  innerHeight: number // layout viewport
  vvHeight: number // visual viewport height
  vvOffsetTop: number
}

export interface SheetGeometry {
  keyboardOpen: boolean
  bottomOffset: number // distance from the screen bottom to the sheet bottom
  free: number // height between the top bar and the sheet's bottom edge
  peek: number
  half: number
  full: number
}

// Sizes the three sheet states from the visual viewport (works for the iOS case where the
// layout viewport keeps its height while the keyboard is up). The top bar is never covered.
export function sheetGeometry({ innerHeight, vvHeight, vvOffsetTop }: ViewportInput): SheetGeometry {
  const inset = Math.max(0, innerHeight - vvHeight - vvOffsetTop)
  const keyboardOpen = inset > KEYBOARD_MIN_INSET
  const bottomOffset = keyboardOpen ? inset : BOTTOM_NAV_H // the keyboard covers the nav
  const free = keyboardOpen ? vvHeight - TOP_BAR_H : vvHeight - TOP_BAR_H - BOTTOM_NAV_H
  const full = free - 8
  const half = Math.min(Math.max(176, Math.round(free * 0.6)), full - 1)
  const peek = Math.min(PEEK_H, half - 1)
  return { keyboardOpen, bottomOffset, free, peek, half, full }
}
