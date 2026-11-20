export type SheetState = "peek" | "half" | "full"
export type SheetTab = "map" | "facilities" | "chat"

const ORDER: SheetState[] = ["peek", "half", "full"]
const FLICK_VELOCITY = 300 // px/s

// The sheet state is the single source of truth; the highlighted tab is derived from it.
export function tabForState(state: SheetState): SheetTab {
  return state === "peek" ? "map" : state === "half" ? "facilities" : "chat"
}

export function stateForTab(tab: SheetTab): SheetState {
  return tab === "map" ? "peek" : tab === "facilities" ? "half" : "full"
}

export function tapHandle(state: SheetState): SheetState {
  return ORDER[(ORDER.indexOf(state) + 1) % ORDER.length]
}

interface SnapInput {
  visible: number // sheet height at release
  velocityY: number // positive = moving down
  current: SheetState
  heights: Record<SheetState, number>
}

export function snapState({ visible, velocityY, current, heights }: SnapInput): SheetState {
  const index = ORDER.indexOf(current)
  if (Math.abs(velocityY) > FLICK_VELOCITY) {
    const step = velocityY < 0 ? 1 : -1
    return ORDER[Math.min(ORDER.length - 1, Math.max(0, index + step))]
  }
  return ORDER.reduce((best, s) =>
    Math.abs(heights[s] - visible) < Math.abs(heights[best] - visible) ? s : best, ORDER[0])
}
