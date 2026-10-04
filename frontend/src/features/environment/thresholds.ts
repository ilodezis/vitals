/* The thresholds form: numbers typed as text, checked before they are sent. The server clamps them
   again; this is so a slip is named on the spot instead of coming back changed. */

import type { EnvSettings, EnvThresholds } from './types'

export type ThresholdForm = Record<keyof EnvThresholds, string>

const KEYS: readonly (keyof EnvThresholds)[] = [
  'co2_ok_max',
  'co2_warn',
  'co2_bad',
  'temp_day_min',
  'temp_day_max',
  'temp_sleep_min',
  'temp_sleep_max',
  'rh_min',
  'rh_max',
  'rh_alert_low',
  'rh_alert_high',
]

/** The ranges that must run low to high, as [lower, higher] keys. */
const ORDERED: readonly (readonly [keyof EnvThresholds, keyof EnvThresholds])[] = [
  ['co2_ok_max', 'co2_warn'],
  ['co2_warn', 'co2_bad'],
  ['temp_day_min', 'temp_day_max'],
  ['temp_sleep_min', 'temp_sleep_max'],
  ['rh_min', 'rh_max'],
  ['rh_alert_low', 'rh_alert_high'],
]

export function thresholdFormOf(th: EnvThresholds): ThresholdForm {
  return Object.fromEntries(KEYS.map((k) => [k, String(th[k])])) as ThresholdForm
}

/** A typed number — a comma or a point for the decimal — or null for anything else. */
export function parseNumber(text: string): number | null {
  const trimmed = text.trim().replace(',', '.')
  if (trimmed === '') return null
  const n = Number(trimmed)
  return Number.isFinite(n) ? n : null
}

/** The form as numbers, or what is wrong with it: `number` (a field is not a number) or `order`
 *  (a range does not run low to high). */
export function sanitizeThresholds(form: ThresholdForm): EnvThresholds | 'number' | 'order' {
  const out: Partial<EnvThresholds> = {}
  for (const k of KEYS) {
    const n = parseNumber(form[k])
    if (n === null) return 'number'
    out[k] = n
  }
  const th = out as EnvThresholds
  return ORDERED.every(([lo, hi]) => th[lo] < th[hi]) ? th : 'order'
}

export function thresholdPatch(th: EnvThresholds): Partial<EnvSettings> {
  return { ...th }
}
