import { describe, expect, it } from "vitest"
import { busyMessage, EMERGENCY_LINE, MAX_AUTO_RETRIES, nextBusyStep } from "./busy"

describe("busyMessage", () => {
  it("rounds a long wait up to whole minutes", () => {
    expect(busyMessage(61_000, 0)).toBe(
      "MediCoord is busy right now. Try again in about 2 minutes. If this is an emergency, call 911.")
  })

  it("uses the singular for one minute", () => {
    expect(busyMessage(60_000, 0)).toBe(
      "MediCoord is busy right now. Try again in about 1 minute. If this is an emergency, call 911.")
  })

  it("says it is retrying when the wait is ten seconds or less", () => {
    expect(busyMessage(10_000, 0)).toBe(
      "High demand, retrying in 10 seconds. If this is an emergency, call 911.")
    expect(busyMessage(1_000, 0)).toBe(
      "High demand, retrying in 1 second. If this is an emergency, call 911.")
  })

  it("never says zero or a negative number of seconds", () => {
    expect(busyMessage(0, 5_000)).toBe(
      "High demand, retrying in 1 second. If this is an emergency, call 911.")
  })

  it("always carries the emergency line", () => {
    expect(busyMessage(3_000, 0).endsWith(EMERGENCY_LINE)).toBe(true)
    expect(busyMessage(600_000, 0).endsWith(EMERGENCY_LINE)).toBe(true)
  })
})

describe("nextBusyStep", () => {
  it("retries by itself after a short wait", () => {
    expect(nextBusyStep(3, 0)).toEqual({ kind: "retry", waitMs: 3_000 })
    expect(nextBusyStep(10, MAX_AUTO_RETRIES - 1)).toEqual({ kind: "retry", waitMs: 10_000 })
  })

  it("stops retrying after the allowed attempts and asks to try again in a minute", () => {
    expect(nextBusyStep(3, MAX_AUTO_RETRIES)).toEqual({ kind: "busy", waitMs: 60_000 })
  })

  it("does not retry by itself on a long wait", () => {
    expect(nextBusyStep(11, 0)).toEqual({ kind: "busy", waitMs: 11_000 })
    expect(nextBusyStep(600, 0)).toEqual({ kind: "busy", waitMs: 600_000 })
  })

  it("treats a missing or zero wait as one second", () => {
    expect(nextBusyStep(0, 0)).toEqual({ kind: "retry", waitMs: 1_000 })
  })
})
