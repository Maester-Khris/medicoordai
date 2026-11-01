import { describe, expect, it } from "vitest"
import { formatWaitAsOf } from "./waitAsOf"

describe("formatWaitAsOf", () => {
  it("shows the hour and minute of the worker's last run", () => {
    expect(formatWaitAsOf("2026-10-10T12:05:00+00:00", "UTC")).toBe("Wait times as of 12:05")
  })

  it("uses a 24 hour clock that starts at 00", () => {
    expect(formatWaitAsOf("2026-10-10T00:07:00+00:00", "UTC")).toBe("Wait times as of 00:07")
  })

  it("converts to the given time zone", () => {
    expect(formatWaitAsOf("2026-10-10T12:05:00+00:00", "America/Toronto")).toBe("Wait times as of 08:05")
  })

  it("is null without a header or with an unreadable one", () => {
    expect(formatWaitAsOf(null)).toBeNull()
    expect(formatWaitAsOf("")).toBeNull()
    expect(formatWaitAsOf("not a date")).toBeNull()
  })
})
