/* Calendar dates as the screens print them: "Sep 29", "Sun, Sep 27", "Yesterday". The API sends
   ISO strings ("2026-09-29"); a date is parsed once at the edge and kept as a local Date so
   a day never slides across midnight in the user's own zone. */

import type { Lang } from './format'

export const DAY_MS = 864e5

const MONTHS_SHORT: Record<Lang, readonly string[]> = {
  ru: ['янв', 'фев', 'мар', 'апр', 'мая', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек'],
  en: ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'],
}
const MONTHS_LONG: Record<Lang, readonly string[]> = {
  ru: ['января', 'февраля', 'марта', 'апреля', 'мая', 'июня', 'июля', 'августа', 'сентября', 'октября', 'ноября', 'декабря'],
  en: ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'],
}
// Index = Date.getDay(): Sunday first.
const WEEKDAYS_SHORT: Record<Lang, readonly string[]> = {
  ru: ['вс', 'пн', 'вт', 'ср', 'чт', 'пт', 'сб'],
  en: ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'],
}
const WEEKDAYS_LONG: Record<Lang, readonly string[]> = {
  ru: ['воскресенье', 'понедельник', 'вторник', 'среда', 'четверг', 'пятница', 'суббота'],
  en: ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'],
}

const at = (list: readonly string[], i: number): string => list[i] ?? ''

/** "2026-09-29" → local midnight of that day. */
export function parseIsoDate(iso: string): Date {
  const [y = 1970, m = 1, d = 1] = iso.slice(0, 10).split('-').map(Number)
  return new Date(y, m - 1, d)
}

/** A local Date → "2026-09-29". */
export function toIsoDate(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

export const startOfDay = (d: Date): Date => new Date(d.getFullYear(), d.getMonth(), d.getDate())

/** Calendar-day arithmetic: 23- and 25-hour days around a clock change still count as one. */
export function addDays(d: Date, n: number): Date {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate() + n)
}

/** Whole calendar days from `a` to `b` (positive when `b` is later). */
export function daysBetween(a: Date, b: Date): number {
  return Math.round((startOfDay(b).getTime() - startOfDay(a).getTime()) / DAY_MS)
}

/** The month alone, short: "Sep". */
export const monthShort = (d: Date, lang: Lang): string => at(MONTHS_SHORT[lang], d.getMonth())

/** The month alone, in full: "September" (Russian uses the genitive form, as after a day number). */
export const monthLong = (d: Date, lang: Lang): string => at(MONTHS_LONG[lang], d.getMonth())

/** "Sep 29" (Russian puts the day first). */
export function shortDate(d: Date, lang: Lang): string {
  const month = at(MONTHS_SHORT[lang], d.getMonth())
  return lang === 'ru' ? `${d.getDate()} ${month}` : `${month} ${d.getDate()}`
}

/** "September 29" (Russian puts the day first). */
export function longDate(d: Date, lang: Lang): string {
  const month = at(MONTHS_LONG[lang], d.getMonth())
  return lang === 'ru' ? `${d.getDate()} ${month}` : `${month} ${d.getDate()}`
}

export const weekdayShort = (d: Date, lang: Lang): string => at(WEEKDAYS_SHORT[lang], d.getDay())

/** "Tuesday" — the weekday named in full, capitalised as a sentence start. */
export function weekdayLong(d: Date, lang: Lang): string {
  const name = at(WEEKDAYS_LONG[lang], d.getDay())
  return name.charAt(0).toUpperCase() + name.slice(1)
}

/** "Sun, Sep 27" — a weekday and a date, for a scrub tip or a row. */
export function weekdayDate(d: Date, lang: Lang): string {
  return `${weekdayShort(d, lang)}, ${shortDate(d, lang)}`
}

/** "Sun, October 4" — a weekday with the month in full, for a date that is named on its own. */
export function weekdayLongDate(d: Date, lang: Lang): string {
  return `${weekdayShort(d, lang)}, ${longDate(d, lang)}`
}

/** "Tuesday, September 29" — the Today kicker. */
export function fullDate(d: Date, lang: Lang): string {
  return `${weekdayLong(d, lang)}, ${longDate(d, lang)}`
}

export interface RelativeLabels {
  today: string
  yesterday: string
}

/** Recent days by name, this week by weekday, older ones by date. */
export function relativeDay(d: Date, today: Date, lang: Lang, labels: RelativeLabels): string {
  const k = daysBetween(d, today)
  if (k === 0) return labels.today
  if (k === 1) return labels.yesterday
  if (k > 1 && k < 7) return weekdayDate(d, lang)
  return shortDate(d, lang)
}

/** When a source last synced: the clock time today, the weekday within the week, else the date. */
export function syncedLabel(isoDateTime: string, today: Date, lang: Lang): string {
  const at = new Date(isoDateTime)
  const k = daysBetween(at, today)
  if (k === 0) return `${String(at.getHours()).padStart(2, '0')}:${String(at.getMinutes()).padStart(2, '0')}`
  if (k > 0 && k < 7) return weekdayShort(at, lang)
  return shortDate(at, lang)
}
