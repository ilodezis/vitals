import { describe, expect, it } from 'vitest'
import environmentView from './useEnvironmentView.ts?raw'
import environmentData from './useEnvironmentData.ts?raw'
import { LIVE_REFETCH_MS, liveOf, periodOf, resolutionFor, SERIES_REFETCH_MS, seriesOf } from './environmentApi'

describe('liveOf', () => {
  it('spells every absent field null, so a screen never tells missing from empty', () => {
    const l = liveOf({
      configured: true,
      station: { status: 'online' },
      now: { co2_zone: 'none' },
      thresholds: {
        co2_ok_max: 800, co2_warn: 1000, co2_bad: 1400, temp_day_min: 18, temp_day_max: 26, temp_sleep_min: 17,
        temp_sleep_max: 20, rh_min: 35, rh_max: 60, rh_alert_low: 30, rh_alert_high: 70,
      },
    })
    expect(l.station).toEqual({ status: 'online', last_seen_at: null, age_s: null, rssi: null, fw: null })
    expect(l.now).toEqual({ co2_ppm: null, temperature_c: null, humidity_pct: null, lux: null, co2_zone: 'none', co2_trend_ppm_per_h: null })
  })

  it('keeps a zero: a CO₂ of nothing and a trend of nothing are readings', () => {
    const l = liveOf({
      configured: true,
      station: { status: 'online', age_s: 0, rssi: 0 },
      now: { co2_ppm: 0, co2_zone: 'good', co2_trend_ppm_per_h: 0 },
      thresholds: {
        co2_ok_max: 800, co2_warn: 1000, co2_bad: 1400, temp_day_min: 18, temp_day_max: 26, temp_sleep_min: 17,
        temp_sleep_max: 20, rh_min: 35, rh_max: 60, rh_alert_low: 30, rh_alert_high: 70,
      },
    })
    expect(l.now.co2_ppm).toBe(0)
    expect(l.now.co2_trend_ppm_per_h).toBe(0)
    expect(l.station.age_s).toBe(0)
  })
})

describe('series and night', () => {
  const thresholds = {
    co2_ok_max: 800, co2_warn: 1000, co2_bad: 1400, temp_day_min: 18, temp_day_max: 26, temp_sleep_min: 17,
    temp_sleep_max: 20, rh_min: 35, rh_max: 60, rh_alert_low: 30, rh_alert_high: 70,
  }
  const window = { start: '2026-10-05T00:00:00Z', end: '2026-10-05T12:00:00Z' }

  it('start from an empty list when the server leaves the points out', () => {
    expect(seriesOf({ resolution: 'minute', coverage_pct: 0, thresholds, window }).points).toEqual([])
    const summary = {
      date: '2026-10-05', window, samples: 0, coverage_pct: 0,
      co2: { minutes_above_bad: 0, minutes_above_warn: 0 }, temperature: {}, humidity: {},
    }
    expect(periodOf({ summary, thresholds }).series).toEqual([])
  })
})

describe('what the live reading asks for', () => {
  it('asks minutes up to two days and hours beyond', () => {
    expect(resolutionFor(6)).toBe('minute')
    expect(resolutionFor(24)).toBe('minute')
    expect(resolutionFor(48)).toBe('minute')
    expect(resolutionFor(72)).toBe('hour')
  })

  it('is renewed at least every ten seconds, the curves every minute', () => {
    expect(LIVE_REFETCH_MS).toBeLessThanOrEqual(10_000)
    expect(SERIES_REFETCH_MS).toBeLessThanOrEqual(60_000)
  })

  it('is never asked for by a tab in the background, nor by a screen that is not in view', () => {
    for (const source of [environmentView, environmentData]) {
      expect(source).toContain('refetchIntervalInBackground: false')
      expect(source).toMatch(/refetchInterval: inView \? \w+ : false/)
    }
  })
})
