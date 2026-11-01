/** "Wait times as of 14:05" from the X-Wait-As-Of header, or null when there is nothing to show. */
export function formatWaitAsOf(iso: string | null, timeZone?: string): string | null {
  if (!iso) return null
  const at = new Date(iso)
  if (Number.isNaN(at.getTime())) return null
  const clock = new Intl.DateTimeFormat("en-CA", {
    hour: "2-digit", minute: "2-digit", hourCycle: "h23", timeZone,
  }).format(at)
  return `Wait times as of ${clock}`
}
