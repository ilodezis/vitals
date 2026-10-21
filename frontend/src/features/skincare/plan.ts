import { addDays, daysBetween, parseIsoDate } from '@/lib/dates'
import type { SkincareDayPlan, SkincareHistoryDay, SkincareLogItem, SkincarePlanItem, SkincareProductItem } from './types'

export const SLOTS = ['morning', 'evening'] as const
export type Slot = (typeof SLOTS)[number]

/** The catalog's weekdays in display order, Monday first: Monday=1 … Sunday=0 (JS `getDay`). */
export const DOW_KEYS: readonly (readonly [number, string])[] = [
  [1, 'mon'],
  [2, 'tue'],
  [3, 'wed'],
  [4, 'thu'],
  [5, 'fri'],
  [6, 'sat'],
  [0, 'sun'],
]

/** A product's slot setting, whichever spelling the view carried it under. */
export const productTime = (p: SkincareProductItem): string => p.defaultTime || p.default_time || p.time || 'evening'

export const productDays = (p: SkincareProductItem): number[] => p.scheduleDays || p.schedule_days || p.days || []

/** Is `p` scheduled for `slot` on weekday `dow`? Inactive products are nowhere. */
export function scheduledIn(p: SkincareProductItem, dow: number, slot: Slot): boolean {
  if (!(p.active || p.on)) return false
  const time = productTime(p)
  return productDays(p).includes(dow) && (time === 'both' || time === slot)
}

export interface Progress {
  done: number
  total: number
}

/** How much of a slot (or a day) is done. A tick off the schedule counts on both sides: it was
 *  done, and it was part of the day. */
export function progressOf(items: readonly SkincarePlanItem[]): Progress {
  return { done: items.filter((i) => i.done).length, total: items.length }
}

export function dayProgress(plan: SkincareDayPlan): Progress {
  return progressOf([...plan.morning, ...plan.evening])
}

/** Share of the *planned* items done over the `days` before `today`, as a percentage; null when
 *  nothing was planned in that window (or tracking had not started). Off-schedule ticks are left
 *  out: doing something extra does not make up for something missed. */
export function adherence(history: readonly SkincareHistoryDay[], today: string, days = 7): number | null {
  const end = parseIsoDate(today)
  const start = addDays(end, -days)
  let planned = 0
  let done = 0
  for (const day of history) {
    const d = parseIsoDate(day.date)
    if (daysBetween(start, d) < 0 || daysBetween(d, end) <= 0) continue
    for (const item of [...day.morning, ...day.evening]) {
      if (!item.planned) continue
      planned += 1
      if (item.done) done += 1
    }
  }
  return planned === 0 ? null : (done / planned) * 100
}

/** The plan with one tick applied — what the screen shows before the server has answered. */
export function withTick(plan: SkincareDayPlan, slot: Slot, productId: number, done: boolean): SkincareDayPlan {
  return {
    ...plan,
    [slot]: plan[slot].map((item) => (item.productId === productId ? { ...item, done } : item)),
  }
}

/** The plan with every open item of `slot` ticked. */
export function withSlotDone(plan: SkincareDayPlan, slot: Slot): SkincareDayPlan {
  return { ...plan, [slot]: plan[slot].map((item) => ({ ...item, done: true })) }
}

/** The hand-filled logs from before the ticks existed. Once tracking starts, a day's log is
 *  derived from its ticks and the history already shows it; listing it again would show the same
 *  day twice in two different shapes. */
export function archivedLogs(
  logs: readonly SkincareLogItem[],
  history: readonly SkincareHistoryDay[],
  plan: SkincareDayPlan,
  today: string,
): SkincareLogItem[] {
  const tickedToday = [...plan.morning, ...plan.evening].some((i) => i.done)
  const oldest = history.length > 0 ? history[history.length - 1]!.date : tickedToday ? today : null
  if (oldest === null) return [...logs]
  return logs.filter((l) => l.date < oldest)
}
