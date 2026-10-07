export function busyMessage(busyUntil: number, now: number): string {
  const minutes = Math.max(1, Math.ceil((busyUntil - now) / 60_000))
  return `MediCoord is busy right now. Try again in about ${minutes} minute${minutes === 1 ? "" : "s"}.`
}
