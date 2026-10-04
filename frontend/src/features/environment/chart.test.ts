import { describe, expect, it } from 'vitest'
import { autoTicks, chartGeometry, hourTicks, type ChartLine } from './chart'

const H = 3_600_000
const MIN = 60_000
const start = new Date(2026, 9, 5, 8, 0).getTime()

const line = (key: string, axis: 'left' | 'right', values: [number, number][]): ChartLine => ({
  key,
  axis,
  points: values.map(([min, v]) => ({ t: start + min * MIN, v })),
})

describe('chartGeometry', () => {
  it('is empty without readings or without a span', () => {
    expect(chartGeometry({ width: 300, start, end: start + H, lines: [line('co2', 'left', [])], gapMs: 4 * MIN }).empty).toBe(true)
    expect(chartGeometry({ width: 0, start, end: start + H, lines: [line('co2', 'left', [[0, 500]])], gapMs: 4 * MIN }).empty).toBe(true)
    expect(chartGeometry({ width: 300, start, end: start, lines: [line('co2', 'left', [[0, 500]])], gapMs: 4 * MIN }).empty).toBe(true)
  })

  it('breaks the line where the station was silent instead of bridging it', () => {
    const g = chartGeometry({
      width: 300,
      start,
      end: start + 2 * H,
      lines: [line('co2', 'left', [[0, 500], [1, 510], [2, 520], [60, 700], [61, 710]])],
      gapMs: 4 * MIN,
    })
    expect(g.paths.co2?.match(/M/g)?.length).toBe(2)
  })

  it('draws a lone reading as a dot, not nothing', () => {
    const g = chartGeometry({ width: 300, start, end: start + H, lines: [line('co2', 'left', [[10, 600]])], gapMs: 4 * MIN })
    expect(g.paths.co2).toMatch(/^M[\d.]+,[\d.]+h0\.01$/)
  })

  it('keeps an included value on the scale, so the warning line is in view when the air is fine', () => {
    const lines = [line('co2', 'left', [[0, 500], [30, 620]])]
    const rules = [{ key: 'co2_warn', axis: 'left' as const, value: 1000 }]
    const flat = chartGeometry({ width: 300, start, end: start + H, lines, rules, gapMs: 4 * MIN })
    expect(flat.rules).toEqual([])
    const kept = chartGeometry({ width: 300, start, end: start + H, lines, rules, include: { left: [400, 1000] }, gapMs: 4 * MIN })
    expect(kept.rules.map((r) => r.key)).toEqual(['co2_warn'])
    // Higher values sit higher on the page (smaller y).
    expect(kept.yOf('left', 1000)).toBeLessThan(kept.yOf('left', 500))
  })

  it('does not stretch a flat day into a storm', () => {
    const g = chartGeometry({
      width: 300,
      start,
      end: start + H,
      lines: [line('temp', 'left', [[0, 21.0], [30, 21.1]])],
      minSpan: { left: 2 },
      gapMs: 4 * MIN,
    })
    const rise = g.yOf('left', 21.0) - g.yOf('left', 21.1)
    expect(rise).toBeLessThan((g.bottom - g.top) * 0.1)
  })

  it('gives a second unit its own scale on the right and makes room for it', () => {
    const g = chartGeometry({
      width: 300,
      start,
      end: start + H,
      lines: [line('temp', 'left', [[0, 20], [30, 22]]), line('rh', 'right', [[0, 40], [30, 50]])],
      gapMs: 4 * MIN,
    })
    expect(g.right).toBeLessThan(300)
    expect(g.rightTicks.length).toBeGreaterThan(0)
    expect(g.leftTicks.length).toBeGreaterThan(0)
  })

  it('places a moment on the clock in proportion', () => {
    const g = chartGeometry({ width: 440, start, end: start + 4 * H, lines: [line('co2', 'left', [[0, 500], [120, 600]])], gapMs: 4 * MIN, left: 40 })
    expect(g.xOf(start)).toBe(40)
    expect(g.xOf(start + 2 * H)).toBeCloseTo(40 + (g.right - 40) / 2)
    expect(g.xOf(start + 4 * H)).toBe(g.right)
  })

  it('uses the clock labels it is given, so it can line up under another chart', () => {
    const ticks = [start + H, start + 3 * H, start + 9 * H]
    const g = chartGeometry({ width: 300, start, end: start + 4 * H, lines: [line('co2', 'left', [[0, 500], [60, 600]])], gapMs: 4 * MIN, ticks })
    // The one outside the span is dropped.
    expect(g.xTicks.map((t) => t.t)).toEqual([start + H, start + 3 * H])
  })

  it('offers the scrub at most a few hundred moments, each with the nearest values', () => {
    const values: [number, number][] = Array.from({ length: 1440 }, (_, i) => [i, 500 + (i % 300)])
    const g = chartGeometry({ width: 300, start, end: start + 24 * H, lines: [line('co2', 'left', values)], gapMs: 4 * MIN })
    expect(g.readings.length).toBeLessThanOrEqual(241)
    expect(g.readings.length).toBeGreaterThan(100)
    expect(g.dotY).toHaveLength(g.readings.length)
    expect(g.readings[0]?.values.co2).toBe(500)
  })

  it('draws an hour range as a band that closes on itself', () => {
    const g = chartGeometry({
      width: 300,
      start,
      end: start + 3 * H,
      lines: [{ key: 'co2', axis: 'left', points: [{ t: start, v: 700 }, { t: start + H, v: 900 }] }],
      band: { axis: 'left', points: [{ t: start, lo: 600, hi: 800 }, { t: start + H, lo: 700, hi: 1100 }] },
      gapMs: 2.5 * H,
    })
    expect(g.band).toMatch(/^M.*Z$/)
  })
})

describe('clock labels', () => {
  it('falls on whole hours of the local clock, counted from midnight', () => {
    const a = new Date(2026, 9, 5, 7, 30).getTime()
    const b = new Date(2026, 9, 5, 20, 0).getTime()
    expect(hourTicks(a, b, 4).map((t) => new Date(t).getHours())).toEqual([8, 12, 16, 20])
  })

  it('crosses midnight', () => {
    const a = new Date(2026, 9, 5, 20, 0).getTime()
    const b = new Date(2026, 9, 6, 4, 0).getTime()
    expect(hourTicks(a, b, 2).map((t) => new Date(t).getHours())).toEqual([20, 22, 0, 2, 4])
  })

  it('picks the smallest step that leaves each label its room', () => {
    const a = new Date(2026, 9, 5, 0, 0).getTime()
    const stepH = (hours: number) => {
      const ticks = autoTicks(a, a + hours * H, 300)
      return ((ticks[1] ?? 0) - (ticks[0] ?? 0)) / H
    }
    expect(stepH(6)).toBe(2)
    expect(stepH(24)).toBe(6)
    expect(stepH(72)).toBe(24)
  })
})
