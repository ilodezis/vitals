import type { Corridor, Goal, GoalForecast } from './types'

// A sentence ends at ".", "!", "?" or "…" followed by whitespace. A decimal point is followed by
// a digit and never by whitespace, so "86.1" stays in one piece.
const SENTENCE_END = /(?<=[.!?…])\s+/

/** The first sentence of the narrative and everything after it: the first is set in the
 *  headline's own colour, the rest a step quieter. */
export function splitNarrative(text: string): { lead: string; note: string } {
  const [lead = '', ...rest] = text.trim().split(SENTENCE_END)
  return { lead, note: rest.join(' ') }
}

/** The goal as distance covered from where he started. `pct` stays on the bar: 0 to 100. */
export function goalProgress(goal: Pick<Goal, 'start_kg' | 'current_kg' | 'target_kg'>): {
  done: number
  total: number
  pct: number
} {
  const done = goal.start_kg - goal.current_kg
  const total = goal.start_kg - goal.target_kg
  const pct = total > 0 ? Math.max(0, Math.min(100, Math.round((done / total) * 100))) : 0
  return { done, total, pct }
}

/** Where a value sits against its corridor; nothing to say without both. */
export function corridorStatus(value: number | null, corridor: Corridor | null): 'below' | 'in' | 'above' | null {
  if (value === null || corridor === null) return null
  if (value < corridor.lo) return 'below'
  return value > corridor.hi ? 'above' : 'in'
}

/** Which sentence tells the forecast, and the number of days it names (0 when it names none). */
export function forecastPhrase(forecast: GoalForecast): { key: string; days: number } {
  const ahead = forecast.days_ahead
  if (ahead === null) return { key: 'app.today.forecast', days: 0 }
  if (ahead > 0) return { key: 'app.today.forecast_early', days: ahead }
  if (ahead < 0) return { key: 'app.today.forecast_late', days: -ahead }
  return { key: 'app.today.forecast_on_time', days: 0 }
}
