const WAIT_TIME_THRESHOLDS: Record<string, number> = {
  '> 10 min': 10,
  '> 25 min': 25,
  '30 min+':  30,
}

export function meetsWaitTimeFilter(waitTime: string, waitMinutes: number | null | undefined): boolean {
  if (waitTime === 'all') return true
  const threshold = WAIT_TIME_THRESHOLDS[waitTime]
  if (threshold === undefined) return true
  return waitMinutes != null && waitMinutes >= threshold
}

/** Popup text for an ER wait: live minutes, a predicted range, or nothing. */
export function formatWaitLabel(
  waitMinutes: number | null | undefined,
  rawWait: string | null | undefined,
  predicted: boolean | undefined,
): string | null {
  if (predicted) {
    const range = rawWait?.trim()
    return range ? `${range} (predicted)` : null
  }
  return waitMinutes != null ? `${waitMinutes} min wait` : null
}
