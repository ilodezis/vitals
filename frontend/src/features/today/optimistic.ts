import type { FeedRow, TodayView } from './types'

/** The day as it will look once a weight is saved — drawn before the server has answered.
 *  Everything a weigh-in touches: the figure, the latest reading, the goal's "now" and the
 *  day's feed. The refetch that follows replaces all of it with what the server made of it. */
export function applyLoggedWeight(view: TodayView, kg: number): TodayView {
  const weighIn: FeedRow = { time: '', kind: 'weight', dot: 'good', text: '', detail: '', value: kg }
  const held = view.feed.some((row) => row.kind === 'weight')
  let feed: FeedRow[]
  if (held) {
    feed = view.feed.map((row) => (row.kind === 'weight' ? { ...row, value: kg } : row))
  } else {
    // The server lists undated rows in the order they were made and the brief's marker last.
    const brief = view.feed.findIndex((row) => row.kind === 'brief')
    feed = brief === -1 ? [...view.feed, weighIn] : [...view.feed.slice(0, brief), weighIn, ...view.feed.slice(brief)]
  }
  return {
    ...view,
    figures: view.figures.map((f) => (f.key === 'weight' ? { ...f, value: kg } : f)),
    latest_weight: { kg, date: view.date },
    goal: view.goal === null ? null : { ...view.goal, current_kg: kg },
    feed,
  }
}
