import { longDate, parseIsoDate } from '@/lib/dates'
import type { Lang } from '@/lib/format'

/** "September 3", with the year when it is not this one — the date a supplement
 *  was started or stopped, as the row shows it. */
export function switchDate(iso: string, todayIso: string, lang: Lang): string {
  const d = parseIsoDate(iso)
  const text = longDate(d, lang)
  return d.getFullYear() === parseIsoDate(todayIso).getFullYear() ? text : `${text} ${d.getFullYear()}`
}
