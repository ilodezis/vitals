import type { EnvLive, EnvPeriod, EnvPoint, EnvSeries, EnvSettings, EnvThresholds } from '@/features/environment/types'

/** The owner's starting thresholds. */
export const THRESHOLDS: EnvThresholds = {
  co2_ok_max: 800,
  co2_warn: 1000,
  co2_bad: 1400,
  temp_day_min: 18,
  temp_day_max: 26,
  temp_sleep_min: 17,
  temp_sleep_max: 20,
  rh_min: 35,
  rh_max: 60,
  rh_alert_low: 30,
  rh_alert_high: 70,
}

export const SETTINGS: EnvSettings = { ...THRESHOLDS, night_window: { start: '00:00', end: '12:00' }, alerts_enabled: true, alert_telegram: true }

export function live(over: { configured?: boolean; station?: Partial<EnvLive['station']>; now?: Partial<EnvLive['now']> } = {}): EnvLive {
  return {
    configured: over.configured ?? true,
    station: { status: 'online', last_seen_at: '2026-10-05T14:03:10', age_s: 4, rssi: -61, fw: 'env-1.1.0', ...over.station },
    now: { co2_ppm: 812, temperature_c: 21.4, humidity_pct: 41.2, lux: null, co2_zone: 'ok', co2_trend_ppm_per_h: 120, ...over.now },
    thresholds: THRESHOLDS,
  }
}

/** Minute points from `start` ("2026-10-05T08:00:00" wall clock), `count` of them, CO₂ climbing `step` per minute. */
export function minutePoints(startHour: number, count: number, from = 600, step = 4): EnvPoint[] {
  return Array.from({ length: count }, (_, i) => {
    const minutes = startHour * 60 + i
    const hh = String(Math.floor(minutes / 60) % 24).padStart(2, '0')
    const mm = String(minutes % 60).padStart(2, '0')
    return {
      ts: `2026-10-05T${hh}:${mm}:00`,
      co2_ppm: from + i * step,
      temperature_c: 20 + Math.sin(i / 40),
      humidity_pct: 42,
      lux: null,
    }
  })
}

export function series(points: EnvPoint[] = minutePoints(8, 120), resolution: EnvSeries['resolution'] = 'minute'): EnvSeries {
  return {
    points,
    resolution,
    coverage_pct: 96,
    thresholds: THRESHOLDS,
    window: { start: '2026-10-05T08:00:00', end: '2026-10-05T10:00:00' },
  }
}

export function night(over: Partial<EnvPeriod['summary']> = {}, points: EnvPoint[] = minutePoints(0, 60)): EnvPeriod {
  return {
    summary: {
      date: '2026-10-05',
      window: { start: '2026-10-05T00:00:00', end: '2026-10-05T12:00:00' },
      coverage_pct: 96,
      samples: 4000,
      co2: { median: 812, p90: 1100, max: 1180, minutes_above_warn: 190, minutes_above_bad: 0 },
      temperature: { min: 19.8, mean: 20.6, max: 21.4 },
      humidity: { min: 38, mean: 41, max: 44 },
      ...over,
    },
    series: points,
    thresholds: THRESHOLDS,
  }
}
