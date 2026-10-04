import { describe, expect, it } from 'vitest'
import { THRESHOLDS } from '@/fixtures/environment'
import { parseNumber, sanitizeThresholds, thresholdFormOf } from './thresholds'

describe('parseNumber', () => {
  it('reads a comma or a point, and refuses what is not a number', () => {
    expect(parseNumber('18,5')).toBe(18.5)
    expect(parseNumber(' 1000 ')).toBe(1000)
    expect(parseNumber('')).toBeNull()
    expect(parseNumber('abc')).toBeNull()
    expect(parseNumber('1e999')).toBeNull()
  })

  it('does not take a cleared field for zero', () => {
    expect(parseNumber('0')).toBe(0)
    expect(parseNumber('')).toBeNull()
  })
})

describe('sanitizeThresholds', () => {
  it('round-trips the stored thresholds', () => {
    expect(sanitizeThresholds(thresholdFormOf(THRESHOLDS))).toEqual(THRESHOLDS)
  })

  it('names a field that is not a number', () => {
    expect(sanitizeThresholds({ ...thresholdFormOf(THRESHOLDS), co2_warn: '' })).toBe('number')
  })

  it.each([
    ['co2_warn', '1500'],
    ['co2_ok_max', '1100'],
    ['temp_day_min', '30'],
    ['temp_sleep_max', '10'],
    ['rh_min', '70'],
    ['rh_alert_low', '80'],
  ] as const)('names a range that does not run low to high (%s = %s)', (key, value) => {
    expect(sanitizeThresholds({ ...thresholdFormOf(THRESHOLDS), [key]: value })).toBe('order')
  })
})
