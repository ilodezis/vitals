import type { Params } from '@/i18n/translate'

export type TFn = (key: string, params?: Params) => string

/** 454 → "7 h 34 min" (the unit words come from the dictionary). */
export function durationText(totalMinutes: number, t: TFn): string {
  const minutes = Math.round(totalMinutes)
  return t('app.duration.hm', { h: Math.floor(minutes / 60), m: String(minutes % 60).padStart(2, '0') })
}

/** 454 → "7 h 34" — the compact form, without the unit at the end. */
export function durationShort(totalMinutes: number, t: TFn): string {
  const minutes = Math.round(totalMinutes)
  return t('app.duration.hm_short', { h: Math.floor(minutes / 60), m: String(minutes % 60).padStart(2, '0') })
}
