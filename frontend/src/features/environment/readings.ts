/* What the station's numbers mean: the instant a timestamp names, the zone a CO₂ reading falls in,
   the word for a temperature, how long ago a reading was. Pure: no drawing, no copy. */

import type { TFn } from '@/lib/units'
import type { Co2Zone, EnvStation, EnvThresholds } from './types'


/** "2026-10-05T14:03:10Z", "…+03:00" or a plain local wall clock "2026-10-05T14:03:10" → the instant
 *  in ms. A time without a zone is the clock the rest of the app already shows as is. */
export function parseTs(ts: string): number | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2}))?/.exec(ts)
  if (m === null) return null
  const timePart = ts.slice(11)
  if (/(?:Z|[+-]\d{2}(?::?\d{2})?)$/i.test(timePart)) {
    const parsed = Date.parse(ts.replace(' ', 'T').replace(/([+-]\d{2})(\d{2})$/, '$1:$2'))
    return Number.isNaN(parsed) ? null : parsed
  }
  return new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]), Number(m[4]), Number(m[5]), Number(m[6] ?? 0)).getTime()
}

/** The zone of a CO₂ reading by the owner's thresholds. */
export function co2ZoneOf(ppm: number | null, th: Pick<EnvThresholds, 'co2_ok_max' | 'co2_warn' | 'co2_bad'>): Co2Zone {
  if (ppm === null) return 'none'
  if (ppm >= th.co2_bad) return 'bad'
  if (ppm >= th.co2_warn) return 'warn'
  if (ppm >= th.co2_ok_max) return 'ok'
  return 'good'
}

/** CO₂ moving by less than this per hour reads as "steady". */
export const STEADY_PPM_PER_H = 30

export type Trend = 'up' | 'down' | 'flat'

export function trendOf(rate: number | null): Trend | null {
  if (rate === null || !Number.isFinite(rate)) return null
  if (Math.abs(rate) < STEADY_PPM_PER_H) return 'flat'
  return rate > 0 ? 'up' : 'down'
}

export type TempVerdict = 'cold' | 'ok' | 'hot'
export type HumidityVerdict = 'dry' | 'ok' | 'humid'

export function tempVerdict(c: number | null, th: Pick<EnvThresholds, 'temp_day_min' | 'temp_day_max'>): TempVerdict | null {
  if (c === null) return null
  if (c < th.temp_day_min) return 'cold'
  return c > th.temp_day_max ? 'hot' : 'ok'
}

export function humidityVerdict(pct: number | null, th: Pick<EnvThresholds, 'rh_min' | 'rh_max'>): HumidityVerdict | null {
  if (pct === null) return null
  if (pct < th.rh_min) return 'dry'
  return pct > th.rh_max ? 'humid' : 'ok'
}

/** Seconds since the station last spoke, as of `nowMs`: the server's age when the answer arrived,
 *  plus the time the answer has been on this device. Reading the clock of the device against the
 *  server's would only measure how far apart the two clocks are. */
export function stationAgeS(station: EnvStation, answeredAtMs: number, nowMs: number): number | null {
  if (station.age_s === null) return null
  return Math.max(0, station.age_s + (nowMs - answeredAtMs) / 1000)
}

/** "12 s", "7 min", "1 h 05 min": how long ago, to the unit that matters. */
export function agoText(ageS: number, t: TFn): string {
  if (ageS < 60) return t('app.env.ago.s', { n: Math.max(0, Math.round(ageS)) })
  const minutes = Math.round(ageS / 60)
  if (minutes < 60) return t('app.duration.min', { m: minutes })
  return t('app.duration.hm', { h: Math.floor(minutes / 60), m: minutes % 60 })
}

/** Minutes → "3 h 10 min" / "40 min". */
export function minutesText(minutes: number, t: TFn): string {
  const m = Math.round(minutes)
  return m >= 60 ? t('app.duration.hm', { h: Math.floor(m / 60), m: m % 60 }) : t('app.duration.min', { m })
}

/** A reading this many seconds old is "just now". */
export const FRESH_S = 5

