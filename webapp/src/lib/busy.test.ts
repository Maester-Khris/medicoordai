import { describe, expect, it } from "vitest"
import { busyMessage } from "./busy"

describe("busyMessage", () => {
  it("rounds the wait up to whole minutes", () => {
    expect(busyMessage(61_000, 0)).toBe("MediCoord is busy right now. Try again in about 2 minutes.")
  })

  it("uses the singular for one minute and never says zero", () => {
    expect(busyMessage(60_000, 0)).toBe("MediCoord is busy right now. Try again in about 1 minute.")
    expect(busyMessage(1_000, 0)).toBe("MediCoord is busy right now. Try again in about 1 minute.")
    expect(busyMessage(0, 5_000)).toBe("MediCoord is busy right now. Try again in about 1 minute.")
  })
})
