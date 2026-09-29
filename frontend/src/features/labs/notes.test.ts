import { describe, expect, it } from 'vitest'
import { labsFixture } from '@/fixtures/labs'
import { markerTrend, rangeText } from './notes'
import { statusOf } from './types'

const marker = (id: string) => {
  const m = labsFixture.markers.find((x) => x.id === id)
  if (m === undefined) throw new Error(id)
  return m
}

describe('lab markers', () => {
  it('reads the status from the reference range', () => {
    expect(statusOf(marker('vitd'))).toBe('low')
    expect(statusOf(marker('tg'))).toBe('ok')
    expect(statusOf({ value: 160, lo: 0, hi: 150 })).toBe('high')
  })

  it('says which way a marker went and whether it is still out of range', () => {
    expect(markerTrend(marker('vitd'))).toEqual({ first: 19, last: 28, direction: 'up', status: 'low', improving: true })
    expect(markerTrend(marker('tg'))).toEqual({ first: 164, last: 128, direction: 'down', status: 'ok', improving: false })
  })

  it('tells improving from worsening only for a result that is out of range', () => {
    expect(markerTrend({ history: [{ dateIso: 'a', value: 10 }, { dateIso: 'b', value: 8 }], value: 8, lo: 30, hi: 100 }).improving).toBe(false)
    expect(markerTrend({ history: [{ dateIso: 'a', value: 180 }, { dateIso: 'b', value: 160 }], value: 160, lo: 0, hi: 150 }).improving).toBe(true)
  })

  it('prints the range with the marker\'s own precision', () => {
    const f = (v: number, d: number) => v.toFixed(d)
    expect(rangeText(marker('vitd'), f)).toBe('30–100')
    expect(rangeText(marker('hba1c'), f)).toBe('4.0–5.7')
  })

  it('has exactly one result outside its range in the fixture, as the screen says', () => {
    expect(labsFixture.markers.filter((m) => statusOf(m) !== 'ok').map((m) => m.id)).toEqual(['vitd'])
  })
})
