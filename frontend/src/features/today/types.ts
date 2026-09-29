import type { RichText } from '@/components/controls/richText'
import type { ScreenId } from '@/components/shell/nav'

/** What `GET /api/v1/today` will hand the screen. Numbers are numbers, dates ISO strings;
 *  the sentences (narrative, feed, alerts) arrive in the user's language, ready to print. */
export interface TodayView {
  /** ISO date of the day shown, and the clock at the moment the view was built. */
  dateIso: string
  now: string
  sync: SyncStamp[]
  narrative: { lead: string; note: string }
  weight: { kg: number; weekDeltaKg: number; todayKg: number; measuredAt: string }
  sleep: { score: number; minutes: number }
  hrv: { ms: number; lo: number; hi: number }
  bodyBattery: { value: number; gained: number }
  intake: { kcal: number; target: number }
  weekChanges: WeekChange[]
  feed: FeedItem[]
  attention: AttentionItem[]
  goal: { startKg: number; targetKg: number; deadlineIso: string; forecast: string }
}

export interface SyncStamp {
  source: string
  /** ISO date-time of the last sync. */
  at: string
  ok: boolean
}

export type MetricKey = 'weight' | 'sleep' | 'hrv' | 'bb'

/** One dumbbell row: last week's value, this week's, on the corridor of the user's own norm. */
export interface WeekChange {
  metric: MetricKey
  unit: string
  from: number
  to: number
  lo: number
  hi: number
  min: number
  max: number
  /** +1 when higher is better, −1 when lower is. */
  better: 1 | -1
  screen: ScreenId
}

export type FeedTone = 'good' | 'cool' | 'accent'

export interface FeedItem {
  time: string
  tone: FeedTone
  text: string
  detail: string
}

export interface AttentionItem {
  tone: 'note' | 'warn' | 'info'
  /** A muted lead-in, printed before the sentence ("Observation · "). */
  lead?: string
  parts: RichText
  /** The small line under it: where the finding came from. */
  evidence?: string
  /** A finding that opens the screen it is about. */
  screen?: ScreenId
}
