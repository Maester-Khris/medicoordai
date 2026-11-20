import { describe, expect, it } from "vitest"
import { snapState, stateForTab, tabForState, tapHandle } from "./sheetState"

const heights = { peek: 96, half: 260, full: 512 }

describe("tab and state stay in sync", () => {
  it("maps every state to one tab and back", () => {
    for (const state of ["peek", "half", "full"] as const) {
      expect(stateForTab(tabForState(state))).toBe(state)
    }
    expect(tabForState("peek")).toBe("map")
    expect(tabForState("half")).toBe("facilities")
    expect(tabForState("full")).toBe("chat")
  })
})

describe("tapHandle", () => {
  it("goes up one state and wraps from full to peek", () => {
    expect(tapHandle("peek")).toBe("half")
    expect(tapHandle("half")).toBe("full")
    expect(tapHandle("full")).toBe("peek")
  })
})

describe("snapState", () => {
  it("snaps to the nearest height when released slowly", () => {
    expect(snapState({ visible: 150, velocityY: 0, current: "full", heights })).toBe("peek")
    expect(snapState({ visible: 230, velocityY: 0, current: "peek", heights })).toBe("half")
    expect(snapState({ visible: 480, velocityY: 0, current: "half", heights })).toBe("full")
  })

  it("a fast flick up moves one state up, a fast flick down one state down", () => {
    expect(snapState({ visible: 100, velocityY: -800, current: "peek", heights })).toBe("half")
    expect(snapState({ visible: 500, velocityY: 800, current: "full", heights })).toBe("half")
  })

  it("never goes past the ends", () => {
    expect(snapState({ visible: 500, velocityY: -800, current: "full", heights })).toBe("full")
    expect(snapState({ visible: 96, velocityY: 800, current: "peek", heights })).toBe("peek")
  })
})
