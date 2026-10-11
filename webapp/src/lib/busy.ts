export const EMERGENCY_LINE = "If this is an emergency, call 911."
export const SHORT_WAIT_SECONDS = 10
export const MAX_AUTO_RETRIES = 3

export interface BusyStep {
  kind: "retry" | "busy"
  waitMs: number
}

export function nextBusyStep(retryAfterSeconds: number, attempt: number): BusyStep {
  const seconds = Math.max(1, retryAfterSeconds)
  if (seconds > SHORT_WAIT_SECONDS) {
    return { kind: "busy", waitMs: seconds * 1000 }
  }
  if (attempt < MAX_AUTO_RETRIES) {
    return { kind: "retry", waitMs: seconds * 1000 }
  }
  return { kind: "busy", waitMs: 60_000 }
}

export function busyMessage(busyUntil: number, now: number): string {
  const remainingSeconds = Math.max(1, Math.ceil((busyUntil - now) / 1000))
  if (remainingSeconds <= SHORT_WAIT_SECONDS) {
    return `High demand, retrying in ${remainingSeconds} second${remainingSeconds === 1 ? "" : "s"}. ${EMERGENCY_LINE}`
  }
  const minutes = Math.max(1, Math.ceil((busyUntil - now) / 60_000))
  return `MediCoord is busy right now. Try again in about ${minutes} minute${minutes === 1 ? "" : "s"}. ${EMERGENCY_LINE}`
}
