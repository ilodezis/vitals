import { describe, expect, it } from 'vitest'
import { doseGeometry, hypnogramGeometry, markerGeometry, niceTicks, trendGeometry } from './geometry'

const d = (m: number, day: number) => new Date(2026, m - 1, day)

describe('niceTicks', () => {
  it('picks round values inside the range', () => {
    expect(niceTicks(84, 96, 3)).toEqual([85, 90, 95])
    expect(niceTicks(0, 250, 3)).toEqual([0, 100, 200])
    for (const v of niceTicks(84.6, 91.2, 4)) {
      expect(v).toBeGreaterThanOrEqual(84.6)
      expect(v).toBeLessThanOrEqual(91.2)
    }
  })
})

describe('trend chart', () => {
  const trend = [
    { date: d(8, 1), kg: 90 },
    { date: d(8, 15), kg: 88.5 },
    { date: d(9, 1), kg: 87 },
  ]
  const base = {
    width: 400,
    phone: true,
    weighings: [{ date: d(8, 15), kg: 88.9 }],
    trend,
    phases: [
      { from: d(7, 5), to: d(7, 20), label: 'A' },
      { from: d(8, 2), to: d(9, 1), label: 'B' },
    ],
    end: d(9, 1),
  }

  it('leaves room for the axis on the right and draws newest at the edge of the line', () => {
    const g = trendGeometry(base)
    expect(g.height).toBe(224)
    expect(g.now?.x).toBeCloseTo(400 - 36, 5)
    expect(g.scrub).toHaveLength(3)
    expect(g.scrub[0]?.x).toBeCloseTo(0, 5)
  })

  it('shades only the dose phases inside the visible range, and names the wide ones', () => {
    const g = trendGeometry(base)
    expect(g.phases.map((p) => p.index)).toEqual([1])
    expect(g.phases[0]?.label).toBe('B')
    expect(trendGeometry({ ...base, width: 400, phone: false }).height).toBe(300)
  })

  it('draws fewer ticks on a phone', () => {
    expect(trendGeometry(base).xTicks).toHaveLength(4)
    expect(trendGeometry({ ...base, phone: false }).xTicks).toHaveLength(7)
  })
})

describe('hypnogram', () => {
  const stages = [2, 2, 3, 3, 3, 2, 1, 0]

  it('merges neighbouring blocks of the same stage', () => {
    const g = hypnogramGeometry(464, stages, 23 * 60 + 40)
    expect(g.blocks.map((b) => b.stage)).toEqual([2, 3, 2, 1, 0])
    expect(g.rows.map((r) => r.stage)).toEqual(['awake', 'rem', 'light', 'deep'])
  })

  it('labels every second hour from the first full hour after lights out', () => {
    const many = Array.from({ length: 91 }, () => 2)
    const g = hypnogramGeometry(464, many, 23 * 60 + 40)
    expect(g.ticks.map((t) => t.minutes)).toEqual([1440, 1560, 1680, 1800])
  })
})

describe('dose chart', () => {
  it('steps up at each phase and names each level once', () => {
    const g = doseGeometry({
      width: 400,
      phone: true,
      phases: [
        { from: d(6, 29), doseMg: 0.25 },
        { from: d(8, 2), doseMg: 0.5 },
      ],
      trend: [
        { date: d(6, 29), kg: 94 },
        { date: d(9, 29), kg: 86.2 },
      ],
      start: d(6, 29),
      end: d(9, 29),
    })
    expect(g.levels.map((l) => l.dose)).toEqual([0.25, 0.5])
    expect(g.levels[0]?.y).toBeGreaterThan(g.levels[1]?.y ?? Infinity)
    expect(g.stepPath.startsWith('M2 146')).toBe(true)
    expect(g.months.map((m) => m.date.getMonth())).toEqual([6, 7, 8])
  })
})

describe('marker chart', () => {
  const base = {
    width: 360,
    phone: true,
    lo: 30,
    hi: 100,
    min: 0,
    max: 120,
    history: [
      { date: d(3, 12), value: 19 },
      { date: d(6, 4), value: 24 },
      { date: d(9, 6), value: 28 },
    ],
  }

  it('marks readings outside the range and the latest one', () => {
    const g = markerGeometry(base)
    expect(g.points.map((p) => p.out)).toEqual([true, true, true])
    expect(g.points.map((p) => p.last)).toEqual([false, false, true])
    expect(g.points[0]?.x).toBeLessThan(g.points[2]?.x ?? 0)
  })

  it('keeps the range band inside the drawn scale and draws the bound the data is near', () => {
    const g = markerGeometry({ ...base, focus: [10, 60] })
    expect(g.band.height).toBeGreaterThan(0)
    expect(g.bounds.map((b) => b.value)).toEqual([30])
  })
})
