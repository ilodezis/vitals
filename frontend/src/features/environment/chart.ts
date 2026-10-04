/* The station's curves on a real clock: one or two value scales, rules for the thresholds, a band
   for an hour's range, and a line that breaks where the station was silent instead of bridging it.
   Geometry only (positions and path strings at the box's pixel width); drawing is `EnvChart`. */

import { linePath, niceTicks, type Point } from '@/components/charts/geometry'

export type Axis = 'left' | 'right'

export interface ChartPoint {
  /** Milliseconds since the epoch. */
  t: number
  v: number
}

export interface ChartLine {
  key: string
  axis: Axis
  points: readonly ChartPoint[]
}

/** A threshold, drawn as a rule across the plot when the scale reaches it. */
export interface ChartRule {
  key: string
  axis: Axis
  value: number
}

/** The span between two readings of the same moments, e.g. an hour's lowest and highest CO₂. */
export interface ChartBand {
  axis: Axis
  points: readonly { t: number; lo: number; hi: number }[]
}

export interface ChartInput {
  width: number
  height?: number
  /** The clock span drawn, in ms. */
  start: number
  end: number
  lines: readonly ChartLine[]
  rules?: readonly ChartRule[]
  band?: ChartBand
  /** Values a scale has to be able to show whatever the data does: a baseline, a warning line. */
  include?: Partial<Record<Axis, readonly number[]>>
  /** The narrowest span a scale may zoom to, so a flat day does not look like a storm. */
  minSpan?: Partial<Record<Axis, number>>
  /** A pause longer than this breaks the line. */
  gapMs: number
  /** Room for the left scale; a chart sitting under the hypnogram uses the hypnogram's own. */
  left?: number
  /** Where the clock labels fall, if not every few hours. */
  ticks?: readonly number[]
}

export interface ChartTick {
  y: number
  value: number
}

export interface ChartRuleOut {
  key: string
  axis: Axis
  y: number
  value: number
}

export interface ChartReading {
  x: number
  t: number
  /** The value of each line near this moment, by key; a line with nothing close is absent. */
  values: Record<string, number>
}

export interface ChartGeometry {
  empty: boolean
  height: number
  left: number
  right: number
  top: number
  bottom: number
  xOf: (t: number) => number
  yOf: (axis: Axis, v: number) => number
  paths: Record<string, string>
  band: string
  rules: ChartRuleOut[]
  leftTicks: ChartTick[]
  rightTicks: ChartTick[]
  xTicks: { x: number; t: number }[]
  readings: ChartReading[]
  /** The y of each reading's first line, for the scrub dot. */
  dotY: number[]
}

const PAD_TOP = 10
const PAD_BOTTOM = 24
const RIGHT_AXIS_W = 36
/** Room each clock label needs. */
const LABEL_W = 54
const STEP_HOURS = [1, 2, 3, 4, 6, 12, 24, 48] as const

/** Local-clock instants every `stepH` hours (counted from midnight), inside [start, end]. */
export function hourTicks(start: number, end: number, stepH: number): number[] {
  const d = new Date(start)
  d.setMinutes(0, 0, 0)
  d.setHours(d.getHours() - (d.getHours() % Math.min(stepH, 24)))
  const out: number[] = []
  // Bounded: a step is at least an hour, a span at most a few days.
  for (let guard = 0; d.getTime() <= end && guard < 400; guard++) {
    if (d.getTime() >= start) out.push(d.getTime())
    d.setHours(d.getHours() + stepH)
  }
  return out
}

/** The clock labels for a span: the smallest step that leaves each label its room. */
export function autoTicks(start: number, end: number, plotWidth: number): number[] {
  const room = Math.max(1, Math.floor(plotWidth / LABEL_W))
  const hours = (end - start) / 3_600_000
  const step = STEP_HOURS.find((s) => hours / s <= room) ?? 48
  return hourTicks(start, end, step)
}

function domainOf(values: readonly number[], include: readonly number[], minSpan: number): [number, number] | null {
  const all = [...values, ...include]
  if (values.length === 0 || all.length === 0) return null
  let lo = Math.min(...all)
  let hi = Math.max(...all)
  if (hi - lo < minSpan) {
    const mid = (hi + lo) / 2
    lo = mid - minSpan / 2
    hi = mid + minSpan / 2
  }
  const pad = (hi - lo) * 0.06
  return [lo - pad, hi + pad]
}

function runsOf(points: readonly ChartPoint[], gapMs: number): ChartPoint[][] {
  const sorted = [...points].sort((a, b) => a.t - b.t)
  const runs: ChartPoint[][] = []
  let run: ChartPoint[] = []
  for (const p of sorted) {
    const last = run[run.length - 1]
    if (last !== undefined && p.t - last.t > gapMs) {
      runs.push(run)
      run = []
    }
    run.push(p)
  }
  if (run.length > 0) runs.push(run)
  return runs
}

export function chartGeometry({ width, height = 190, start, end, lines, rules = [], band, include = {}, minSpan = {}, gapMs, left = 40, ticks }: ChartInput): ChartGeometry {
  const hasRight = lines.some((l) => l.axis === 'right' && l.points.length > 0)
  const right = hasRight ? width - RIGHT_AXIS_W : width
  const bottom = height - PAD_BOTTOM
  const empty: ChartGeometry = {
    empty: true,
    height,
    left,
    right,
    top: PAD_TOP,
    bottom,
    xOf: () => left,
    yOf: () => bottom,
    paths: {},
    band: '',
    rules: [],
    leftTicks: [],
    rightTicks: [],
    xTicks: [],
    readings: [],
    dotY: [],
  }
  if (width <= 0 || end <= start || lines.every((l) => l.points.length === 0)) return empty

  const domains: Record<Axis, [number, number] | null> = { left: null, right: null }
  for (const axis of ['left', 'right'] as const) {
    const values = lines.filter((l) => l.axis === axis).flatMap((l) => l.points.map((p) => p.v))
    if (band !== undefined && band.axis === axis) for (const p of band.points) values.push(p.lo, p.hi)
    domains[axis] = domainOf(values, include[axis] ?? [], minSpan[axis] ?? 1)
  }

  const xOf = (t: number) => left + ((t - start) / (end - start)) * (right - left)
  const yOf = (axis: Axis, v: number) => {
    const [lo, hi] = domains[axis] ?? [0, 1]
    return bottom - ((v - lo) / (hi - lo)) * (bottom - PAD_TOP)
  }

  const paths: Record<string, string> = {}
  for (const line of lines) {
    paths[line.key] = runsOf(line.points, gapMs)
      .map((run) => {
        const pts: Point[] = run.map((p) => [xOf(p.t), yOf(line.axis, p.v)])
        const first = pts[0] as Point
        return pts.length === 1 ? `M${first[0]},${first[1]}h0.01` : linePath(pts)
      })
      .join(' ')
  }

  let bandPath = ''
  if (band !== undefined && domains[band.axis] !== null) {
    const sorted = [...band.points].sort((a, b) => a.t - b.t)
    const runs: (typeof sorted)[] = []
    let run: typeof sorted = []
    for (const p of sorted) {
      const last = run[run.length - 1]
      if (last !== undefined && p.t - last.t > gapMs) {
        runs.push(run)
        run = []
      }
      run.push(p)
    }
    if (run.length > 0) runs.push(run)
    bandPath = runs
      .map((r) => {
        const upper = r.map((p) => `${xOf(p.t).toFixed(1)},${yOf(band.axis, p.hi).toFixed(1)}`)
        const lower = r
          .map((p) => `${xOf(p.t).toFixed(1)},${yOf(band.axis, p.lo).toFixed(1)}`)
          .reverse()
        return `M${upper.join('L')}L${lower.join('L')}Z`
      })
      .join(' ')
  }

  const ruleOut: ChartRuleOut[] = []
  for (const rule of rules) {
    const d = domains[rule.axis]
    if (d !== null && rule.value >= d[0] && rule.value <= d[1]) ruleOut.push({ key: rule.key, axis: rule.axis, y: yOf(rule.axis, rule.value), value: rule.value })
  }

  const axisTicks = (axis: Axis): ChartTick[] => {
    const d = domains[axis]
    if (d === null) return []
    return niceTicks(d[0], d[1], 4).map((value) => ({ y: yOf(axis, value), value }))
  }

  const xTicks = (ticks ?? autoTicks(start, end, right - left)).filter((t) => t >= start && t <= end).map((t) => ({ x: xOf(t), t }))

  // What the scrub lands on: at most ~240 moments across the span, where anything was measured.
  const moments = [...new Set(lines.flatMap((l) => l.points.map((p) => p.t)))].sort((a, b) => a - b)
  const bucket = Math.max((end - start) / 240, 1)
  const picked: number[] = []
  let lastBucket = -1
  for (const t of moments) {
    const b = Math.floor((t - start) / bucket)
    if (b !== lastBucket) {
      picked.push(t)
      lastBucket = b
    }
  }
  const sortedLines = lines.map((l) => ({ ...l, points: [...l.points].sort((a, b) => a.t - b.t) }))
  const readings: ChartReading[] = []
  const dotY: number[] = []
  for (const t of picked) {
    const values: Record<string, number> = {}
    let firstY: number | null = null
    for (const l of sortedLines) {
      let best: ChartPoint | null = null
      for (const p of l.points) if (best === null || Math.abs(p.t - t) < Math.abs(best.t - t)) best = p
      if (best !== null && Math.abs(best.t - t) <= gapMs) {
        values[l.key] = best.v
        if (firstY === null) firstY = yOf(l.axis, best.v)
      }
    }
    if (firstY === null) continue
    readings.push({ x: xOf(t), t, values })
    dotY.push(firstY)
  }

  return {
    empty: false,
    height,
    left,
    right,
    top: PAD_TOP,
    bottom,
    xOf,
    yOf,
    paths,
    band: bandPath,
    rules: ruleOut,
    leftTicks: axisTicks('left'),
    rightTicks: axisTicks('right'),
    xTicks,
    readings,
    dotY,
  }
}
