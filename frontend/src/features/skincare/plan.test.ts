import { describe, expect, it } from 'vitest'
import { adherence, archivedLogs, dayProgress, scheduledIn, withSlotDone, withTick } from './plan'
import type { SkincareDayPlan, SkincareHistoryDay, SkincareLogItem, SkincarePlanItem, SkincareProductItem } from './types'

const item = (productId: number, done: boolean, planned = true): SkincarePlanItem => ({
  productId,
  name: `p${productId}`,
  flag: null,
  planned,
  done,
  doneAt: null,
})

const day = (date: string, morning: SkincarePlanItem[], evening: SkincarePlanItem[]): SkincareHistoryDay => ({ date, morning, evening })

const product = (over: Partial<SkincareProductItem>): SkincareProductItem => ({
  id: 1,
  name: 'x',
  type: 't',
  defaultTime: 'evening',
  time: 'evening',
  scheduleDays: [3],
  days: [3],
  active: true,
  on: true,
  ...over,
})

describe('scheduledIn', () => {
  it('puts "both" in both slots and an inactive product nowhere', () => {
    const both = product({ defaultTime: 'both' })
    expect(scheduledIn(both, 3, 'morning')).toBe(true)
    expect(scheduledIn(both, 3, 'evening')).toBe(true)
    expect(scheduledIn(both, 4, 'evening')).toBe(false)
    expect(scheduledIn(product({ active: false, on: false }), 3, 'evening')).toBe(false)
  })
})

describe('progress', () => {
  it('counts an off-schedule tick as part of the day', () => {
    const plan: SkincareDayPlan = { morning: [item(1, true)], evening: [item(2, false), item(3, true, false)] }
    expect(dayProgress(plan)).toEqual({ done: 2, total: 3 })
  })
})

describe('adherence', () => {
  it('is the share of planned items done in the week before today', () => {
    const history = [
      day('2026-10-20', [item(1, true)], [item(2, false)]),
      day('2026-10-19', [item(1, true)], [item(2, true), item(9, true, false)]),
      day('2026-10-13', [item(1, false)], []), // eight days back: outside the window
    ]
    expect(adherence(history, '2026-10-21')).toBe(75)
  })

  it('is null when nothing was planned', () => {
    expect(adherence([], '2026-10-21')).toBeNull()
  })
})

describe('ticks', () => {
  const plan: SkincareDayPlan = { morning: [item(1, false)], evening: [item(1, false), item(2, false)] }

  it('ticks one product in one slot only', () => {
    const next = withTick(plan, 'evening', 1, true)
    expect(next.evening.map((i) => i.done)).toEqual([true, false])
    expect(next.morning[0]!.done).toBe(false)
  })

  it('ticks a whole slot', () => {
    expect(withSlotDone(plan, 'evening').evening.every((i) => i.done)).toBe(true)
  })
})

describe('archivedLogs', () => {
  const log = (date: string): SkincareLogItem => ({
    id: 1,
    date,
    retinoid: true,
    azelaic: false,
    peel: false,
    niacinamideSpf: false,
    moisturizer: false,
    vitaminC: false,
    benzoylPeroxide: false,
  })
  const empty: SkincareDayPlan = { morning: [], evening: [] }

  it('keeps only the days before tracking started', () => {
    const logs = [log('2026-10-20'), log('2026-10-01')]
    const history = [day('2026-10-20', [], [item(1, true)]), day('2026-10-18', [], [item(1, false)])]
    expect(archivedLogs(logs, history, empty, '2026-10-21').map((l) => l.date)).toEqual(['2026-10-01'])
  })

  it('keeps everything while nothing was ever ticked', () => {
    expect(archivedLogs([log('2026-10-20')], [], empty, '2026-10-21')).toHaveLength(1)
  })

  it('starts the cut at today when today holds the first tick', () => {
    const plan: SkincareDayPlan = { morning: [item(1, true)], evening: [] }
    expect(archivedLogs([log('2026-10-21'), log('2026-10-20')], [], plan, '2026-10-21').map((l) => l.date)).toEqual(['2026-10-20'])
  })
})
