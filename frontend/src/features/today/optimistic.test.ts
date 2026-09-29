import { describe, expect, it } from 'vitest'
import { sampleTodayView } from '@/fixtures/todayView'
import { applyLoggedWeight } from './optimistic'

describe('applyLoggedWeight', () => {
  it('puts the new weight everywhere the screen shows it', () => {
    const next = applyLoggedWeight(sampleTodayView(), 85.5)

    expect(next.figures.find((f) => f.key === 'weight')?.value).toBe(85.5)
    expect(next.latest_weight).toEqual({ kg: 85.5, date: '2026-09-29' })
    expect(next.goal?.current_kg).toBe(85.5)
  })

  it('adds the weigh-in to the day, above the undated brief row', () => {
    const next = applyLoggedWeight(sampleTodayView(), 85.5)

    expect(next.feed.map((r) => r.kind)).toEqual(['meal', 'weight', 'brief'])
    expect(next.feed[1]).toEqual({ time: '', kind: 'weight', dot: 'good', text: '', detail: '', value: 85.5 })
  })

  it('appends the row when the day has no brief', () => {
    const view = sampleTodayView({ feed: [] })

    expect(applyLoggedWeight(view, 85.5).feed.map((r) => r.kind)).toEqual(['weight'])
  })

  it('corrects the weigh-in already there instead of adding a second one', () => {
    const once = applyLoggedWeight(sampleTodayView(), 85.5)
    const twice = applyLoggedWeight(once, 85.9)

    expect(twice.feed.filter((r) => r.kind === 'weight')).toEqual([
      { time: '', kind: 'weight', dot: 'good', text: '', detail: '', value: 85.9 },
    ])
  })

  it('leaves a day with no goal without one', () => {
    expect(applyLoggedWeight(sampleTodayView({ goal: null }), 85.5).goal).toBeNull()
  })

  it('does not touch the view it was given', () => {
    const view = sampleTodayView()
    const before = structuredClone(view)

    applyLoggedWeight(view, 85.5)

    expect(view).toEqual(before)
  })
})
