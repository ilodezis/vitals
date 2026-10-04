import { describe, expect, it } from 'vitest'
import { minutePoints, THRESHOLDS } from '@/fixtures/environment'
import { chartGeometry } from './chart'
import { climateModel, co2Model, gapFor, pointsOf, sleepTempModel, spanOf, statsOf, zoneStops } from './model'
import type { EnvPoint } from './types'

describe('pointsOf', () => {
  it('drops a reading the station could not take, and a time it could not give', () => {
    const pts: EnvPoint[] = [
      { ts: '2026-10-05T10:00:00Z', co2_ppm: 600 },
      { ts: '2026-10-05T10:01:00Z', co2_ppm: null },
      { ts: '2026-10-05T10:02:00Z' },
      { ts: 'garbage', co2_ppm: 700 },
    ]
    expect(pointsOf(pts, (p) => p.co2_ppm)).toEqual([{ t: Date.UTC(2026, 9, 5, 10, 0), v: 600 }])
  })
})

describe('spanOf', () => {
  it('takes the response window, else what its points cover', () => {
    const pts = minutePoints(8, 30)
    expect(spanOf({ start: '2026-10-05T07:00:00', end: '2026-10-05T09:00:00' }, pts)).toEqual([
      new Date(2026, 9, 5, 7, 0).getTime(),
      new Date(2026, 9, 5, 9, 0).getTime(),
    ])
    const [a, b] = spanOf(undefined, pts) ?? [0, 0]
    expect(b - a).toBe(29 * 60_000)
  })

  it('widens a single reading so there is something to draw it on', () => {
    const [a, b] = spanOf(undefined, minutePoints(8, 1)) ?? [0, 0]
    expect(b).toBeGreaterThan(a)
  })

  it('has none without readings', () => {
    expect(spanOf(undefined, [])).toBeNull()
  })
})

describe('co2Model', () => {
  it('always keeps the baseline and the warning line on the scale', () => {
    const m = co2Model(minutePoints(8, 30, 500, 1), THRESHOLDS, 'minute')
    expect(m.include.left).toEqual([400, 1000])
  })

  it('brings the poor line in once the air nears it', () => {
    const m = co2Model(minutePoints(8, 30, 900, 10), THRESHOLDS, 'minute')
    expect(m.include.left).toContain(1400)
  })

  it('shows an hour range only for hourly points', () => {
    const hourly: EnvPoint[] = [{ ts: '2026-10-05T10:00:00Z', co2_ppm: 800, co2_min: 600, co2_max: 1200 }]
    expect(co2Model(hourly, THRESHOLDS, 'hour').band?.points).toHaveLength(1)
    expect(co2Model(hourly, THRESHOLDS, 'minute').band).toBeUndefined()
  })

  it('counts the peak of an hour, not only its mean, when deciding to show the poor line', () => {
    const hourly: EnvPoint[] = [{ ts: '2026-10-05T10:00:00Z', co2_ppm: 700, co2_min: 600, co2_max: 1300 }]
    expect(co2Model(hourly, THRESHOLDS, 'hour').include.left).toContain(1400)
  })
})

describe('the other models', () => {
  it('puts temperature on the left scale and humidity on the right', () => {
    const m = climateModel(minutePoints(8, 10), THRESHOLDS, 'minute')
    expect(m.lines.map((l) => [l.key, l.axis])).toEqual([
      ['temp', 'left'],
      ['rh', 'right'],
    ])
  })

  it('reads the bedroom against the sleep range, which stays on the scale', () => {
    const m = sleepTempModel(minutePoints(0, 10), THRESHOLDS)
    expect(m.include.left).toEqual([17, 20])
    expect(m.rules.map((r) => r.value)).toEqual([17, 20])
  })

  it('breaks a line over a longer pause the sparser the points are', () => {
    expect(gapFor('raw')).toBeLessThan(gapFor('minute'))
    expect(gapFor('minute')).toBeLessThan(gapFor('hour'))
  })
})

describe('zoneStops', () => {
  const start = new Date(2026, 9, 5, 8).getTime()
  const g = chartGeometry({
    width: 300,
    start,
    end: start + 3_600_000,
    lines: [{ key: 'co2', axis: 'left', points: [{ t: start, v: 450 }, { t: start + 1_800_000, v: 1600 }] }],
    include: { left: [400, 1000, 1400] },
    gapMs: 240_000,
  })

  it('changes colour at the thresholds, worst at the top', () => {
    const stops = zoneStops(g, THRESHOLDS)
    expect(stops.map((s) => s.color)).toEqual([
      'var(--bad)',
      'var(--bad)',
      'var(--warn)',
      'var(--warn)',
      'var(--fg-2)',
      'var(--fg-2)',
      'var(--good)',
      'var(--good)',
    ])
    const offsets = stops.map((s) => s.offset)
    expect([...offsets].sort((a, b) => a - b)).toEqual(offsets)
    expect(offsets[0]).toBe(0)
    expect(offsets.at(-1)).toBe(1)
  })
})

describe('statsOf', () => {
  it('sums up the points drawn: CO2 median and peak, the span of temperature and humidity', () => {
    const pts: EnvPoint[] = [
      { ts: '2026-10-05T01:00:00Z', co2_ppm: 600, temperature_c: 20.5, humidity_pct: 40 },
      { ts: '2026-10-05T01:01:00Z', co2_ppm: 1000, temperature_c: 19.5, humidity_pct: 44 },
      { ts: '2026-10-05T01:02:00Z', co2_ppm: 800, temperature_c: null, humidity_pct: 42 },
    ]
    expect(statsOf(pts)).toEqual({
      co2: { median: 800, max: 1000 },
      temperature: { min: 19.5, max: 20.5 },
      humidity: { min: 40, max: 44 },
    })
  })

  it('takes the middle of two for an even count', () => {
    const pts: EnvPoint[] = [
      { ts: '2026-10-05T01:00:00Z', co2_ppm: 600 },
      { ts: '2026-10-05T01:01:00Z', co2_ppm: 1000 },
    ]
    expect(statsOf(pts).co2.median).toBe(800)
  })

  it('has nothing to say about no points', () => {
    expect(statsOf([])).toEqual({ co2: { median: null, max: null }, temperature: { min: null, max: null }, humidity: { min: null, max: null } })
  })
})
