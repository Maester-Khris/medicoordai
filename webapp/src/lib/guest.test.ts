// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { captureInternalToken, getGuestId, getInternalToken } from "./guest"

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/

describe("getGuestId", () => {
  beforeEach(() => localStorage.clear())
  afterEach(() => vi.restoreAllMocks())

  it("creates a uuid once and returns the same one afterwards", () => {
    const first = getGuestId()
    expect(first).toMatch(UUID)
    expect(getGuestId()).toBe(first)
    expect(localStorage.getItem("mc_guest_id")).toBe(first)
  })

  it("returns a fresh id when storage holds garbage", () => {
    localStorage.setItem("mc_guest_id", "<script>")
    const id = getGuestId()
    expect(id).toMatch(UUID)
    expect(localStorage.getItem("mc_guest_id")).toBe(id)
  })

  it("falls back to memory when storage throws", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("blocked") })
    const first = getGuestId()
    expect(first).toMatch(UUID)
    expect(getGuestId()).toBe(first)
  })
})

describe("internal token", () => {
  beforeEach(() => localStorage.clear())

  it("is captured from ?internal= and kept", () => {
    captureInternalToken("?internal=s3cret&x=1")
    expect(getInternalToken()).toBe("s3cret")
    captureInternalToken("")
    expect(getInternalToken()).toBe("s3cret")
  })

  it("is null when never set", () => {
    expect(getInternalToken()).toBeNull()
  })
})
