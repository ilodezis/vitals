import { describe, expect, it } from 'vitest'
import { clockOf, curvesGeometry, minuteOf } from './curves'

describe('minute axis', () => {
  it('reads the wall clock off the string, across midnight', () => {
    expect(minuteOf('2026-09-29T23:40:00', '2026-09-29')).toBe(23 * 60 + 40)
    expect(minuteOf('2026-09-30T01:10:00', '2026-09-29')).toBe(24 * 60 + 70)
    expect(minuteOf('nonsense', '2026-09-29')).toBeNull()
  })

  it('prints minutes past a midnight as a clock', () => {
    expect(clockOf(24 * 60 + 70)).toBe('01:10')
    expect(clockOf(59.6)).toBe('01:00')
  })
})

describe('curvesGeometry', () => {
  const at = (hh: number, mm: number, v: number) => ({ ts: `2026-09-29T${String(hh).padStart(2, '0')}:${String(mm).padStart(2, '0')}:00`, value: v })

  it('is empty without points', () => {
    expect(curvesGeometry({ width: 300, series: [{ key: 'a', axis: 'left', points: [] }] }).empty).toBe(true)
  })

  it('breaks the line where nothing was measured instead of bridging it', () => {
    const g = curvesGeometry({
      width: 300,
      series: [{ key: 'stress', axis: 'left', points: [at(8, 0, 20), at(8, 3, 22), at(11, 0, 40), at(11, 3, 42)] }],
      leftRange: [0, 100],
    })
    expect(g.paths.stress?.match(/M/g)?.length).toBe(2)
  })

  it('gives a second unit its own scale on the right', () => {
    const g = curvesGeometry({
      width: 300,
      series: [
        { key: 'bb', axis: 'left', points: [at(8, 0, 50), at(9, 0, 60)] },
        { key: 'hr', axis: 'right', points: [at(8, 0, 60), at(9, 0, 90)] },
      ],
      leftRange: [0, 100],
    })
    expect(g.right).toBeLessThan(300)
    expect(g.rightTicks.length).toBeGreaterThan(0)
    expect(g.leftTicks.map((tick) => tick.value)).toContain(100)
  })

  it('reads every series at a moment for the scrub', () => {
    const g = curvesGeometry({
      width: 300,
      series: [
        { key: 'a', axis: 'left', points: [at(8, 0, 1), at(8, 5, 2)] },
        { key: 'b', axis: 'left', points: [at(8, 5, 7)] },
      ],
    })
    const r = g.readings.find((x) => clockOf(x.minute) === '08:05')
    expect(r?.values).toEqual({ a: 2, b: 7 })
  })
})
