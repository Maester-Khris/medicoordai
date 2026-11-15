import { describe, expect, it } from "vitest"
import { EMERGENCY_COPY } from "./emergency"
import { SEVERITY_LABEL } from "./severityLabels"

describe("EMERGENCY_COPY", () => {
  it("is the approved wording", () => {
    expect(EMERGENCY_COPY).toEqual({
      button: "Call 911",
      title: "Call 911 now",
      body: "Dial 911 on your phone and tell the operator where you are. Stay on the line until they say you can hang up. If someone is with you, ask them to stay with you.",
      footer: "MediCoord does not place the call or contact anyone for you.",
      headerLink: "Emergency? Call 911",
    })
  })
})

describe("SEVERITY_LABEL", () => {
  it("uses only the four schema words, in capitals", () => {
    expect(SEVERITY_LABEL).toEqual({
      routine: "ROUTINE",
      moderate: "MODERATE",
      urgent: "URGENT",
      emergent: "EMERGENT",
    })
  })
})
