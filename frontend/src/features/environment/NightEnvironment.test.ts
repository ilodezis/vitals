import { describe, expect, it } from 'vitest'
import { hypnogramClock } from './NightEnvironment'

describe('hypnogramClock', () => {
  it('puts a night that begins after midnight on the day it is filed under', () => {
    const { start, end, ticks } = hypnogramClock('2026-10-05', 30, 12 * 12)
    expect(new Date(start).getDate()).toBe(5)
    expect(new Date(start).getHours()).toBe(0)
    expect(new Date(start).getMinutes()).toBe(30)
    expect(end - start).toBe(12 * 3_600_000)
    // Whole hours, every second one, as the hypnogram prints them.
    expect(ticks.map((t) => new Date(t).getHours())).toEqual([1, 3, 5, 7, 9, 11])
  })

  it('puts a night that begins in the evening on the day before', () => {
    const { start, end } = hypnogramClock('2026-10-05', 23 * 60 + 40, 8 * 12)
    expect(new Date(start).getDate()).toBe(4)
    expect(new Date(start).getHours()).toBe(23)
    expect(new Date(end).getDate()).toBe(5)
    expect(new Date(end).getHours()).toBe(7)
    expect(new Date(end).getMinutes()).toBe(40)
  })
})
