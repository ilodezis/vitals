/* Chart geometry, apart from any drawing. Every chart is laid out at the real pixel width of
   its box: these functions take that width and the data and return where things go. The
   numbers (paddings, heights, tick counts, opacities) are the mockup's. d3 supplies the
   scales, the tick choice and the monotone curve; nothing here touches the DOM. */

import { scaleLinear } from 'd3-scale'
import { area as d3area, curveMonotoneX, line as d3line } from 'd3-shape'
import { DAY_MS } from '@/lib/dates'

export type Point = readonly [number, number]

const smooth = d3line<Point>().curve(curveMonotoneX).digits(1)
const straight = d3line<Point>().digits(1)

/** A smooth path through the points (monotone: it never overshoots a reading). */
export const smoothPath = (points: readonly Point[]): string => smooth(points as Point[]) ?? ''
/** A path with straight segments. */
export const linePath = (points: readonly Point[]): string => straight(points as Point[]) ?? ''
/** The smooth path closed down to a baseline, for the quiet fill under a line. */
export function areaPath(points: readonly Point[], baseline: number): string {
  return (
    d3area<Point>()
      .curve(curveMonotoneX)
      .digits(1)
      .x((p) => p[0])
      .y0(baseline)
      .y1((p) => p[1])(points as Point[]) ?? ''
  )
}

/** Round tick values inside [lo, hi], about `count` of them. */
export function niceTicks(lo: number, hi: number, count: number): number[] {
  return scaleLinear().domain([lo, hi]).ticks(count).filter((v) => v >= lo - 1e-9 && v <= hi + 1e-9)
}

export interface ScrubPoint {
  x: number
  y: number
  /** The reading, and the date it belongs to — what the tip prints. */
  value: number
  date: Date
}

/* ---------- Weight and its 7-day trend ---------- */
export interface TrendInput {
  width: number
  phone: boolean
  /** Weighings and the trend, oldest first, already limited to the visible range. */
  weighings: readonly { date: Date; kg: number }[]
  trend: readonly { date: Date; kg: number }[]
  phases: readonly { from: Date; to: Date; label: string }[]
  /** The last day drawn: today. */
  end: Date
}

export interface TrendGeometry {
  width: number
  height: number
  top: number
  bottom: number
  yTicks: { value: number; y: number }[]
  xTicks: { date: Date; x: number; anchor: 'start' | 'middle' | 'end' }[]
  phases: { index: number; x: number; width: number; label: string | null }[]
  trendPath: string
  areaPath: string
  dots: { x: number; y: number }[]
  now: { x: number; y: number } | null
  scrub: ScrubPoint[]
}

export function trendGeometry(input: TrendInput): TrendGeometry {
  const { width, phone, weighings, trend, phases, end } = input
  const height = phone ? 224 : 300
  const [L, R, T, B] = [0, 36, 26, 26]
  const start = trend[0]?.date ?? weighings[0]?.date ?? end
  const x0 = start.getTime()
  const x1 = end.getTime()

  const visibleWeighings = weighings.filter((p) => {
    const t = p.date.getTime()
    return t >= x0 && t <= x1
  })

  const all = [...trend.map((p) => p.kg), ...visibleWeighings.map((p) => p.kg)]
  const lo = all.length === 0 ? 0 : Math.floor(Math.min(...all) - 0.4)
  const hi = all.length === 0 ? 1 : Math.ceil(Math.max(...all) + 0.4)
  const X = scaleLinear().domain([x0, x1 === x0 ? x0 + DAY_MS : x1]).range([L, width - R])
  const Y = scaleLinear().domain([lo, hi]).range([height - B, T])

  const trendPoints: Point[] = trend.map((p) => [X(p.date.getTime()), Y(p.kg)])
  const last = trendPoints[trendPoints.length - 1]
  const nx = phone ? 3 : 6

  const bands: TrendGeometry['phases'] = []
  phases.forEach((ph, index) => {
    const a = X(Math.max(ph.from.getTime(), x0))
    const b = X(Math.min(ph.to.getTime(), x1))
    if (b <= a) return
    bands.push({ index, x: a, width: b - a, label: b - a > 64 ? ph.label : null })
  })

  return {
    width,
    height,
    top: T,
    bottom: B,
    yTicks: niceTicks(lo, hi, phone ? 3 : 4).map((value) => ({ value, y: Y(value) })),
    xTicks: Array.from({ length: nx + 1 }, (_, i) => ({
      date: new Date(x0 + ((x1 - x0) * i) / nx),
      x: X(x0 + ((x1 - x0) * i) / nx),
      anchor: i === 0 ? ('start' as const) : i === nx ? ('end' as const) : ('middle' as const),
    })),
    phases: bands,
    trendPath: smoothPath(trendPoints),
    areaPath: trendPoints.length > 1 ? areaPath(trendPoints, height - B) : '',
    dots: visibleWeighings.map((p) => ({ x: X(p.date.getTime()), y: Y(p.kg) })),
    now: last === undefined ? null : { x: last[0], y: last[1] },
    scrub: trend.map((p, i) => ({ x: (trendPoints[i] as Point)[0], y: (trendPoints[i] as Point)[1], value: p.kg, date: p.date })),
  }
}

/* ---------- The night, as a hypnogram ---------- */
export const HYPNOGRAM_STAGES = ['awake', 'rem', 'light', 'deep'] as const

export interface HypnogramGeometry {
  width: number
  height: number
  rowHeight: number
  left: number
  rows: { stage: (typeof HYPNOGRAM_STAGES)[number]; labelY: number; lineY: number }[]
  outline: string
  blocks: { x: number; y: number; width: number; height: number; stage: number }[]
  /** Clock ticks every second hour, in minutes since midnight. */
  ticks: { minutes: number; x: number }[]
}

export function hypnogramGeometry(width: number, stages: readonly number[], startMinutes: number): HypnogramGeometry {
  const [H, T, B, L] = [132, 4, 22, 64]
  const rh = (H - T - B) / 4
  const n = stages.length
  const bw = n === 0 ? 0 : (width - L) / n

  let outline = ''
  stages.forEach((stage, i) => {
    const y = T + rh * stage + rh / 2
    outline += (i > 0 ? `L${L + i * bw} ${y}` : `M${L} ${y}`) + `L${L + (i + 1) * bw} ${y}`
  })

  const blocks: HypnogramGeometry['blocks'] = []
  for (let i = 0; i < n; ) {
    const stage = stages[i] as number
    let j = i
    while (j < n && stages[j] === stage) j++
    blocks.push({ x: L + i * bw + 0.5, y: T + rh * stage + 4, width: Math.max(1, (j - i) * bw - 1), height: rh - 8, stage })
    i = j
  }

  const ticks: HypnogramGeometry['ticks'] = []
  for (let t = Math.ceil(startMinutes / 60) * 60; t - startMinutes <= n * 5 - 30; t += 120) {
    ticks.push({ minutes: t, x: L + ((t - startMinutes) / 5) * bw })
  }

  return {
    width,
    height: H,
    rowHeight: rh,
    left: L,
    rows: HYPNOGRAM_STAGES.map((stage, i) => ({ stage, labelY: T + rh * i + rh / 2 + 4, lineY: T + rh * i + rh })),
    outline,
    blocks,
    ticks,
  }
}

/* ---------- Dose and weight ---------- */
export interface DoseGeometry {
  width: number
  height: number
  bottom: number
  /** Dose levels drawn as rules, top to bottom. */
  levels: { dose: number; y: number }[]
  stepPath: string
  weightPath: string
  first: { x: number; y: number; kg: number } | null
  last: { x: number; y: number; kg: number } | null
  months: { date: Date; x: number }[]
}

export function doseGeometry(input: {
  width: number
  phone: boolean
  phases: readonly { from: Date; doseMg: number }[]
  trend: readonly { date: Date; kg: number }[]
  start: Date
  end: Date
}): DoseGeometry {
  const { width, phone, phases, trend, start, end } = input
  const height = phone ? 170 : 210
  const [T, B, L, R] = [20, 24, 2, 38]
  const X = scaleLinear().domain([start.getTime(), end.getTime()]).range([L, width - R])

  // Weight scale: derived from trend data with padding, instead of hardcoded [85, 95]
  const weights = trend.map((p) => p.kg)
  const minW = weights.length > 0 ? Math.min(...weights) : 85
  const maxW = weights.length > 0 ? Math.max(...weights) : 95
  const span = Math.max(2, maxW - minW)
  const pad = Math.max(0.5, span * 0.1)
  const wLo = Math.floor(minW - pad)
  const wHi = Math.ceil(maxW + pad)
  const Yw = scaleLinear().domain([wLo, wHi]).range([height - B, T])

  // Dose levels: equal steps so levels (e.g. 0.25 and 0.5) do not clump together
  const sortedDoses = [...new Set(phases.map((p) => p.doseMg).filter((d) => d > 0))].sort((a, b) => a - b)
  const K = sortedDoses.length
  const availH = height - B - T

  const doseYMap = new Map<number, number>()
  sortedDoses.forEach((d, i) => {
    const y = (height - B) - ((i + 1) / (K + 0.35)) * availH
    doseYMap.set(d, y)
  })

  const Yd = (dose: number): number => {
    if (dose <= 0) return height - B
    const exact = doseYMap.get(dose)
    if (exact !== undefined) return exact
    if (K === 0) return height - B
    if (dose < sortedDoses[0]!) {
      const y0 = doseYMap.get(sortedDoses[0]!)!
      return (height - B) + (y0 - (height - B)) * (dose / sortedDoses[0]!)
    }
    for (let i = 0; i < K - 1; i++) {
      const d0 = sortedDoses[i]!
      const d1 = sortedDoses[i + 1]!
      if (dose >= d0 && dose <= d1) {
        const y0 = doseYMap.get(d0)!
        const y1 = doseYMap.get(d1)!
        return y0 + ((dose - d0) / (d1 - d0)) * (y1 - y0)
      }
    }
    const lastDose = sortedDoses[K - 1]!
    const lastY = doseYMap.get(lastDose)!
    return Math.max(T, lastY - ((dose - lastDose) / lastDose) * (availH / (K + 0.35)))
  }

  // Thin out levels if any two adjacent labels are closer than MIN_LABEL_GAP px
  const MIN_LABEL_GAP = 16
  const rawLevels = sortedDoses.map((dose) => ({ dose, y: doseYMap.get(dose)! }))
  const filteredLevels: { dose: number; y: number }[] = []
  for (let i = 0; i < rawLevels.length; i++) {
    const curr = rawLevels[i]!
    const prev = filteredLevels[filteredLevels.length - 1]
    if (prev === undefined || Math.abs(curr.y - prev.y) >= MIN_LABEL_GAP || i === rawLevels.length - 1) {
      filteredLevels.push(curr)
    }
  }

  let step = `M${L} ${height - B}`
  phases.forEach((p, i) => {
    const x = X(p.from.getTime())
    step += i === 0 ? `L${x} ${height - B}` : ''
    step += `L${x} ${Yd(p.doseMg)}`
    step += `L${X((phases[i + 1]?.from ?? end).getTime())} ${Yd(p.doseMg)}`
  })

  const wp: Point[] = trend.map((p) => [X(p.date.getTime()), Yw(p.kg)])
  const firstP = trend[0]
  const lastP = trend[trend.length - 1]
  const months: DoseGeometry['months'] = []
  for (let d = new Date(start.getFullYear(), start.getMonth() + 1, 1); d <= end; d = new Date(d.getFullYear(), d.getMonth() + 1, 1)) {
    months.push({ date: d, x: X(d.getTime()) })
  }

  return {
    width,
    height,
    bottom: height - B,
    levels: filteredLevels,
    stepPath: step,
    weightPath: smoothPath(wp),
    first: firstP === undefined ? null : { x: X(firstP.date.getTime()), y: Yw(firstP.kg), kg: firstP.kg },
    last: lastP === undefined ? null : { x: X(lastP.date.getTime()), y: Yw(lastP.kg), kg: lastP.kg },
    months,
  }
}

/* ---------- One lab marker over time ---------- */
export interface MarkerInput {
  width: number
  phone: boolean
  lo: number
  hi: number
  min: number
  max: number
  history: readonly { date: Date; value: number }[]
  /** Show this stretch of the scale instead of one derived from the data and the range. */
  focus?: readonly [number, number]
}

export interface MarkerGeometry {
  width: number
  height: number
  band: { x: number; y: number; width: number; height: number; labelY: number }
  bounds: { value: number; y: number }[]
  points: { x: number; y: number; value: number; date: Date; out: boolean; last: boolean }[]
  path: string
}

export function markerGeometry(input: MarkerInput): MarkerGeometry {
  const { width, phone, lo, hi, min, max, history, focus } = input
  const height = phone ? 150 : 190
  const [T, B, L, R] = [18, 24, 8, 44]
  const values = history.map((h) => h.value)
  let dLo: number
  let dHi: number
  if (focus !== undefined) {
    ;[dLo, dHi] = focus
  } else {
    dLo = Math.min(lo, ...values)
    dHi = Math.max(hi, ...values)
    const pad = (dHi - dLo) * 0.12
    dLo = Math.max(min, dLo - pad)
    dHi = Math.min(max, dHi + pad)
  }
  const t0 = history[0]?.date.getTime() ?? 0
  const t1 = history[history.length - 1]?.date.getTime() ?? 1
  const X = scaleLinear().domain([t0, t1 === t0 ? t0 + DAY_MS : t1]).range([L + 18, width - R - 18])
  const Y = scaleLinear().domain([dLo, dHi]).range([height - B, T]).clamp(true)

  const ry0 = Y(Math.min(hi, dHi))
  const ry1 = Y(Math.max(lo, dLo))
  const pts = history.map((h, i) => ({
    x: X(h.date.getTime()),
    y: Y(h.value),
    value: h.value,
    date: h.date,
    out: h.value < lo || h.value > hi,
    last: i === history.length - 1,
  }))
  return {
    width,
    height,
    band: { x: L, y: ry0, width: width - L - R + 8, height: Math.max(0, ry1 - ry0), labelY: ry0 + 16 },
    bounds: [
      ...(lo > dLo ? [{ value: lo, y: Y(lo) }] : []),
      ...(hi < dHi ? [{ value: hi, y: Y(hi) }] : []),
    ],
    points: pts,
    path: linePath(pts.map((p) => [p.x, p.y] as const)),
  }
}
