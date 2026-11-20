import { describe, expect, it } from "vitest"
import { nextHighlightRequest } from "./highlightRequest"

describe("nextHighlightRequest", () => {
  it("first request starts at 1", () => {
    expect(nextHighlightRequest(null, "f1")).toEqual({ id: "f1", requestId: 1 })
  })

  it("the same id again gets a new requestId", () => {
    const first = nextHighlightRequest(null, "f1")
    const again = nextHighlightRequest(first, "f1")
    expect(again.id).toBe(first.id)
    expect(again.requestId).toBe(first.requestId + 1)
  })

  it("a different id also increments", () => {
    const first = nextHighlightRequest(null, "f1")
    expect(nextHighlightRequest(first, "f2")).toEqual({ id: "f2", requestId: 2 })
  })
})
