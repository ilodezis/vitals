/* Curves over a day or a night: a linear minute axis, so a gap reads as the hour it really was,
   and a line that breaks where the watch measured nothing instead of bridging it. Up to two
   scales: a series either shares the left one (0–100 scores side by side) or gets the right. */

import { linePath, niceTicks, type Point } from './geometry'

export interface CurvePointIn {
  /** Local wall-clock ISO datetime, as the API sends it ("2026-09-29T23:40:00"). */
  ts: string
  value: number
}

export interface CurveSeriesIn {
  key: string
  axis: 'left' | 'right'
  points: readonly CurvePointIn[]
}

export interface CurvesInput {
  width: number
  height?: number
  series: readonly CurveSeriesIn[]
  /** A fixed left scale (stress and Body Battery are both 0–100); otherwise it fits the data. */
  leftRange?: readonly [number, number]
  /** A pause longer than this many minutes breaks the line. */
  gapMinutes?: number
}

export interface CurveTick {
  x: number
  label: string
}

export interface CurveAxisTick {
  y: number
  value: number
}

export interface CurveReading {
  x: number
  /** Minutes since the first day's midnight; the clock is this modulo a day. */
  minute: number
  /** The value of each series near this moment, by key; a series with nothing close is absent. */
  values: Record<string, number>
}

export interface CurvesGeometry {
  height: number
  left: number
  right: number
  paths: Record<string, string>
  xTicks: CurveTick[]
  leftTicks: CurveAxisTick[]
  rightTicks: CurveAxisTick[]
  readings: CurveReading[]
  /** The y of each reading's first present series, for the scrub dot. */
  dotY: number[]
  empty: boolean
}

const PAD_TOP = 10
const PAD_BOTTOM = 24
const AXIS_W = 30

/** "2026-09-29T23:40:00" → minutes since the local midnight of `base` ("2026-09-29"). Read off the
 *  string: the value is already the wall clock, parsing it through a zone would move it. */
export function minuteOf(ts: string, base: string): number | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(ts)
  const b = /^(\d{4})-(\d{2})-(\d{2})/.exec(base)
  if (m === null || b === null) return null
  const day = Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3]))
  const baseDay = Date.UTC(Number(b[1]), Number(b[2]) - 1, Number(b[3]))
  return Math.round((day - baseDay) / 60000) + Number(m[4]) * 60 + Number(m[5])
}

/** 1510 → "01:10": minutes past a midnight as a clock. */
export function clockOf(minute: number): string {
  const total = ((Math.round(minute) % 1440) + 1440) % 1440
  return `${String(Math.floor(total / 60)).padStart(2, '0')}:${String(total % 60).padStart(2, '0')}`
}

function range(values: readonly number[]): [number, number] {
  let lo = Math.min(...values)
  let hi = Math.max(...values)
  if (lo === hi) {
    lo -= 1
    hi += 1
  }
  const pad = (hi - lo) * 0.08
  return [lo - pad, hi + pad]
}

export function curvesGeometry({ width, height = 200, series, leftRange, gapMinutes = 20 }: CurvesInput): CurvesGeometry {
  const present = series.filter((s) => s.points.length > 0)
  const base = present.flatMap((s) => s.points.map((p) => p.ts)).sort()[0] ?? ''
  const timed = present.map((s) => ({
    ...s,
    pts: s.points
      .map((p) => ({ t: minuteOf(p.ts, base), v: p.value }))
      .filter((p): p is { t: number; v: number } => p.t !== null)
      .sort((a, b) => a.t - b.t),
  }))
  const all = timed.flatMap((s) => s.pts)
  const hasRight = timed.some((s) => s.axis === 'right')
  const left = AXIS_W
  const right = hasRight ? width - AXIS_W : width
  const empty: CurvesGeometry = { height, left, right, paths: {}, xTicks: [], leftTicks: [], rightTicks: [], readings: [], dotY: [], empty: true }
  if (all.length === 0 || width <= 0) return empty

  const t0 = Math.min(...all.map((p) => p.t))
  const t1 = Math.max(...all.map((p) => p.t))
  const span = Math.max(t1 - t0, 1)
  const x = (t: number) => left + ((t - t0) / span) * (right - left)
  const plotBottom = height - PAD_BOTTOM

  const scaleFor = (axis: 'left' | 'right'): [number, number] | null => {
    if (axis === 'left' && leftRange !== undefined) return [leftRange[0], leftRange[1]]
    const values = timed.filter((s) => s.axis === axis).flatMap((s) => s.pts.map((p) => p.v))
    return values.length === 0 ? null : range(values)
  }
  const scales = { left: scaleFor('left'), right: scaleFor('right') }
  const y = (axis: 'left' | 'right', v: number) => {
    const [lo, hi] = scales[axis] ?? [0, 1]
    return plotBottom - ((v - lo) / (hi - lo)) * (plotBottom - PAD_TOP)
  }

  const paths: Record<string, string> = {}
  for (const s of timed) {
    const runs: Point[][] = []
    let run: Point[] = []
    let last: number | null = null
    for (const p of s.pts) {
      if (last !== null && p.t - last > gapMinutes) {
        runs.push(run)
        run = []
      }
      run.push([x(p.t), y(s.axis, p.v)])
      last = p.t
    }
    runs.push(run)
    paths[s.key] = runs
      .filter((r) => r.length > 0)
      .map((r) => (r.length === 1 ? `M${(r[0] as Point)[0]},${(r[0] as Point)[1]}h0.01` : linePath(r)))
      .join(' ')
  }

  // Whole hours, about six across whatever the span is.
  const step = Math.max(60, Math.ceil(span / 6 / 60) * 60)
  const xTicks: CurveTick[] = []
  for (let t = Math.ceil(t0 / step) * step; t <= t1; t += step) xTicks.push({ x: x(t), label: clockOf(t) })

  const axisTicks = (axis: 'left' | 'right'): CurveAxisTick[] => {
    const sc = scales[axis]
    if (sc === null) return []
    return niceTicks(sc[0], sc[1], 4)
      .filter((v) => v >= sc[0] && v <= sc[1])
      .map((v) => ({ y: y(axis, v), value: v }))
  }

  // A reading every five minutes where anything was measured: what the scrub lands on.
  const buckets = [...new Set(all.map((p) => Math.round(p.t / 5) * 5))].sort((a, b) => a - b)
  const readings: CurveReading[] = []
  const dotY: number[] = []
  for (const t of buckets) {
    const values: Record<string, number> = {}
    let firstY: number | null = null
    for (const s of timed) {
      let best: { t: number; v: number } | null = null
      for (const p of s.pts) if (best === null || Math.abs(p.t - t) < Math.abs(best.t - t)) best = p
      if (best !== null && Math.abs(best.t - t) <= Math.min(gapMinutes, 10)) {
        values[s.key] = best.v
        if (firstY === null) firstY = y(s.axis, best.v)
      }
    }
    if (firstY === null) continue
    readings.push({ x: x(t), minute: t, values })
    dotY.push(firstY)
  }

  return { height, left, right, paths, xTicks, leftTicks: axisTicks('left'), rightTicks: axisTicks('right'), readings, dotY, empty: false }
}
