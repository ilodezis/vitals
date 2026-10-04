/* From the API's points to what a chart draws: which curves, on which scale, with which rules. */

import type { ChartBand, ChartGeometry, ChartLine, ChartPoint, ChartRule } from './chart'
import { parseTs } from './readings'
import type { EnvPoint, EnvResolution, EnvThresholds, EnvWindow } from './types'

export const COLOR = {
  co2: 'var(--fg-2)',
  temp: 'var(--violet)',
  rh: 'var(--cool)',
  good: 'var(--good)',
  warn: 'var(--warn)',
  bad: 'var(--bad)',
  neutral: 'var(--fg-2)',
} as const

/** The usual CO₂ of outdoor air: the floor a CO₂ scale starts from. */
export const CO2_BASELINE = 400

export interface ChartModel {
  lines: ChartLine[]
  rules: ChartRule[]
  band?: ChartBand
  include: { left?: number[]; right?: number[] }
  minSpan: { left?: number; right?: number }
  gapMs: number
}

/** One metric of the series as chart points; a reading the station could not take is not a point. */
export function pointsOf(points: readonly EnvPoint[], pick: (p: EnvPoint) => number | null | undefined): ChartPoint[] {
  const out: ChartPoint[] = []
  for (const p of points) {
    const t = parseTs(p.ts)
    const v = pick(p)
    if (t !== null && v !== null && v !== undefined && Number.isFinite(v)) out.push({ t, v })
  }
  return out
}

export interface PointStats {
  co2: { median: number | null; max: number | null }
  temperature: { min: number | null; max: number | null }
  humidity: { min: number | null; max: number | null }
}

/** What the points on a chart add up to: the CO2 median and peak, the span of temperature and humidity. */
export function statsOf(points: readonly EnvPoint[]): PointStats {
  const values = (pick: (p: EnvPoint) => number | null | undefined) => pointsOf(points, pick).map((p) => p.v)
  const co2 = values((p) => p.co2_ppm).sort((a, b) => a - b)
  const mid = Math.floor(co2.length / 2)
  const median = co2.length === 0 ? null : co2.length % 2 === 1 ? (co2[mid] as number) : ((co2[mid - 1] as number) + (co2[mid] as number)) / 2
  const span = (v: number[]) => ({ min: v.length === 0 ? null : Math.min(...v), max: v.length === 0 ? null : Math.max(...v) })
  return {
    co2: { median, max: co2.length === 0 ? null : (co2[co2.length - 1] as number) },
    temperature: span(values((p) => p.temperature_c)),
    humidity: span(values((p) => p.humidity_pct)),
  }
}

/** The clock span of a response: its own window, else what its points cover. */
export function spanOf(window: EnvWindow | undefined, points: readonly EnvPoint[]): [number, number] | null {
  const a = window === undefined ? null : parseTs(window.start)
  const b = window === undefined ? null : parseTs(window.end)
  if (a !== null && b !== null && b > a) return [a, b]
  const times = points.map((p) => parseTs(p.ts)).filter((t): t is number => t !== null)
  if (times.length === 0) return null
  const lo = Math.min(...times)
  const hi = Math.max(...times)
  return hi > lo ? [lo, hi] : [lo - 30 * 60_000, hi + 30 * 60_000]
}

/** A pause in the readings longer than this breaks the line, by how often a point is made. */
const GAP_MS: Record<EnvResolution, number> = { raw: 90_000, minute: 4 * 60_000, hour: 2.5 * 3_600_000 }

export const gapFor = (resolution: EnvResolution): number => GAP_MS[resolution]

export function co2Model(points: readonly EnvPoint[], th: EnvThresholds, resolution: EnvResolution): ChartModel {
  const hourly = resolution === 'hour'
  const co2 = pointsOf(points, (p) => p.co2_ppm)
  const top = co2.reduce((m, p) => Math.max(m, p.v), 0)
  const peak = hourly ? pointsOf(points, (p) => p.co2_max).reduce((m, p) => Math.max(m, p.v), top) : top
  // The warning line is always in view; the "poor" line joins it once the air gets near it.
  const include = [CO2_BASELINE, th.co2_warn, ...(peak >= th.co2_warn ? [th.co2_bad] : [])]
  const band = hourly ? bandOf(points) : undefined
  return {
    lines: [{ key: 'co2', axis: 'left', points: co2 }],
    rules: [
      { key: 'co2_warn', axis: 'left', value: th.co2_warn },
      { key: 'co2_bad', axis: 'left', value: th.co2_bad },
    ],
    band,
    include: { left: include },
    minSpan: { left: 200 },
    gapMs: gapFor(resolution),
  }
}

function bandOf(points: readonly EnvPoint[]): ChartBand | undefined {
  const out: { t: number; lo: number; hi: number }[] = []
  for (const p of points) {
    const t = parseTs(p.ts)
    if (t !== null && p.co2_min != null && p.co2_max != null) out.push({ t, lo: p.co2_min, hi: p.co2_max })
  }
  return out.length === 0 ? undefined : { axis: 'left', points: out }
}

/** Temperature on the left scale, humidity on the right; a comfort edge is drawn once the data nears it. */
export function climateModel(points: readonly EnvPoint[], th: EnvThresholds, resolution: EnvResolution): ChartModel {
  return {
    lines: [
      { key: 'temp', axis: 'left', points: pointsOf(points, (p) => p.temperature_c) },
      { key: 'rh', axis: 'right', points: pointsOf(points, (p) => p.humidity_pct) },
    ],
    rules: [
      { key: 'temp_min', axis: 'left', value: th.temp_day_min },
      { key: 'temp_max', axis: 'left', value: th.temp_day_max },
      { key: 'rh_min', axis: 'right', value: th.rh_min },
      { key: 'rh_max', axis: 'right', value: th.rh_max },
    ],
    include: {},
    minSpan: { left: 2, right: 10 },
    gapMs: gapFor(resolution),
  }
}

/** The bedroom's temperature against the range it is comfortable to sleep in. */
export function sleepTempModel(points: readonly EnvPoint[], th: EnvThresholds, resolution: EnvResolution = 'minute'): ChartModel {
  return {
    lines: [{ key: 'temp', axis: 'left', points: pointsOf(points, (p) => p.temperature_c) }],
    rules: [
      { key: 'temp_min', axis: 'left', value: th.temp_sleep_min },
      { key: 'temp_max', axis: 'left', value: th.temp_sleep_max },
    ],
    include: { left: [th.temp_sleep_min, th.temp_sleep_max] },
    minSpan: { left: 2 },
    gapMs: gapFor(resolution),
  }
}

export interface GradientStop {
  offset: number
  color: string
}

/** The CO₂ line's colours by the zone it is in: hard stops at the thresholds, top to bottom. */
export function zoneStops(g: Pick<ChartGeometry, 'yOf' | 'top' | 'bottom'>, th: Pick<EnvThresholds, 'co2_ok_max' | 'co2_warn' | 'co2_bad'>): GradientStop[] {
  const span = Math.max(1, g.bottom - g.top)
  const at = (v: number) => Math.min(1, Math.max(0, (g.yOf('left', v) - g.top) / span))
  const bad = at(th.co2_bad)
  const warn = at(th.co2_warn)
  const ok = at(th.co2_ok_max)
  return [
    { offset: 0, color: COLOR.bad },
    { offset: bad, color: COLOR.bad },
    { offset: bad, color: COLOR.warn },
    { offset: warn, color: COLOR.warn },
    { offset: warn, color: COLOR.neutral },
    { offset: ok, color: COLOR.neutral },
    { offset: ok, color: COLOR.good },
    { offset: 1, color: COLOR.good },
  ]
}
