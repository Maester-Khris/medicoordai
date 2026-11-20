import type { Severity } from "../../../shared/types"

// One label per severity on every platform: the schema word, no ESI numbers.
export const SEVERITY_LABEL: Record<Severity, string> = {
  routine: "ROUTINE",
  moderate: "MODERATE",
  urgent: "URGENT",
  emergent: "EMERGENT",
}
