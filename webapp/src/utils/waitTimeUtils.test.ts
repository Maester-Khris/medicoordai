import { describe, it, expect } from 'vitest'
import { meetsWaitTimeFilter, formatWaitLabel } from './waitTimeUtils'

describe('meetsWaitTimeFilter', () => {
  it('passes everything when waitTime is all', () => {
    expect(meetsWaitTimeFilter('all', null)).toBe(true)
    expect(meetsWaitTimeFilter('all', undefined)).toBe(true)
    expect(meetsWaitTimeFilter('all', 5)).toBe(true)
  })

  it('excludes facilities with no wait data once a threshold is active', () => {
    expect(meetsWaitTimeFilter('> 10 min', null)).toBe(false)
    expect(meetsWaitTimeFilter('> 10 min', undefined)).toBe(false)
  })

  it('excludes facilities below the threshold', () => {
    expect(meetsWaitTimeFilter('> 10 min', 5)).toBe(false)
    expect(meetsWaitTimeFilter('> 25 min', 24)).toBe(false)
    expect(meetsWaitTimeFilter('30 min+', 29)).toBe(false)
  })

  it('includes facilities at or above the threshold', () => {
    expect(meetsWaitTimeFilter('> 10 min', 10)).toBe(true)
    expect(meetsWaitTimeFilter('> 25 min', 30)).toBe(true)
    expect(meetsWaitTimeFilter('30 min+', 30)).toBe(true)
  })
})

describe("formatWaitLabel", () => {
  it("shows live minutes", () => {
    expect(formatWaitLabel(42, "42 min", false)).toBe("42 min wait")
    expect(formatWaitLabel(0, null, false)).toBe("0 min wait")
  })

  it("shows a predicted range with its marker", () => {
    expect(formatWaitLabel(null, "45m–2h", true)).toBe("45m–2h (predicted)")
  })

  it("shows nothing when there is no data", () => {
    expect(formatWaitLabel(null, null, false)).toBeNull()
    expect(formatWaitLabel(undefined, undefined, undefined)).toBeNull()
  })

  it("shows nothing for a predicted row without text", () => {
    expect(formatWaitLabel(null, "  ", true)).toBeNull()
  })
})
