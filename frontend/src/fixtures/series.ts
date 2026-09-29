/* Demo series behind the screen fixtures: one realistic morning, Tue 29 Sep 2026, 08:14.
   Seeded, so the app reads the same on every load — and the same as the redesign mockup
   (docs/design/mockup/src/data.js), which draws from the same generator in the same order.
   These stand in for the API until each screen is served from it. */

import { addDays, daysBetween } from '@/lib/dates'

export const FIXTURE_TODAY = new Date(2026, 8, 29)
export const FIXTURE_NOW = '08:14'

function rng(seed: number): () => number {
  let s = seed
  return () => ((s = (s * 16807) % 2147483647) - 1) / 2147483646
}
const random = rng(42)
const noise = (amplitude: number): number => (random() - 0.5) * 2 * amplitude

export interface DatedValue {
  date: Date
  value: number
}

/* ---------- Weight: 1 Apr → 29 Sep ---------- */
const WEIGHT_KNOTS: readonly (readonly [Date, number])[] = [
  [new Date(2026, 3, 1), 96.4],
  [new Date(2026, 5, 29), 94.0],
  [new Date(2026, 6, 19), 92.6],
  [new Date(2026, 7, 3), 90.8],
  [new Date(2026, 8, 1), 88.5],
  [FIXTURE_TODAY, 86.1],
]

function baseWeight(d: Date): number {
  for (let i = 1; i < WEIGHT_KNOTS.length; i++) {
    const [a, wa] = WEIGHT_KNOTS[i - 1] as readonly [Date, number]
    const [b, wb] = WEIGHT_KNOTS[i] as readonly [Date, number]
    if (d <= b) {
      const t = (d.getTime() - a.getTime()) / (b.getTime() - a.getTime())
      const e = t * t * (3 - 2 * t) * 0.35 + t * 0.65
      return wa + (wb - wa) * e
    }
  }
  return 86.1
}

/** Weighings — not every day, and fewer of them the further back. */
export const weighings: DatedValue[] = []
for (let d = new Date(2026, 3, 1); d <= FIXTURE_TODAY; d = addDays(d, 1)) {
  const k = daysBetween(d, FIXTURE_TODAY)
  if (k > 0 && random() < (k < 40 ? 0.28 : 0.5)) continue
  let w = baseWeight(d) + noise(0.38)
  if (k === 0) w = 86.1
  weighings.push({ date: new Date(d), value: Number(w.toFixed(1)) })
}

/** The 7-day average on calendar days. */
function averageAt(d: Date): number | null {
  const inWindow = weighings.filter((p) => {
    const k = daysBetween(p.date, d)
    return k >= 0 && k < 7
  })
  return inWindow.length === 0 ? null : inWindow.reduce((s, p) => s + p.value, 0) / inWindow.length
}

export const weightTrend: DatedValue[] = []
for (let d = new Date(2026, 3, 1); d <= FIXTURE_TODAY; d = addDays(d, 1)) {
  const v = averageAt(d)
  if (v !== null) weightTrend.push({ date: new Date(d), value: v })
}

export const latestWeight = (weighings[weighings.length - 1] as DatedValue).value

/* ---------- Recovery: 14 nights ---------- */
export interface NightRow {
  date: Date
  sleep: number
  hrv: number
  rhr: number
  stress: number
  steps: number
  bb: number
}

export const nights: NightRow[] = []
for (let i = 13; i >= 0; i--) {
  const late = i <= 2
  nights.push({
    date: addDays(FIXTURE_TODAY, -i),
    sleep: Math.round(i === 0 ? 82 : 76 + noise(9) + (i < 7 ? 3 : 0)),
    hrv: Math.round(i === 0 ? 46 : late ? 45 + noise(2) : 54 + noise(4)),
    rhr: Math.round(i === 0 ? 52 : late ? 53 + noise(1) : 50 + noise(2)),
    stress: Math.round(i === 0 ? 23 : 26 + noise(7)),
    steps: Math.round(i === 0 ? 1715 : 8200 + noise(3600)),
    bb: Math.round(i === 0 ? 94 : 82 + noise(10)),
  })
}

/** Hypnogram 23:40 → 07:14 in 5-minute blocks. 0 awake, 1 REM, 2 light, 3 deep. */
export const hypnogram: number[] = (() => {
  const plan: readonly (readonly [number, number])[] = [
    [2, 3], [3, 6], [2, 3], [3, 5], [2, 4], [1, 2], [0, 1],
    [2, 4], [3, 4], [2, 5], [1, 4], [2, 4], [3, 2], [2, 5], [1, 5], [0, 1],
    [2, 6], [1, 5], [2, 4], [0, 1], [2, 3], [1, 6], [2, 2], [0, 1],
  ]
  const out: number[] = []
  for (const [stage, blocks] of plan) for (let i = 0; i < blocks; i++) out.push(stage)
  return out
})()

/** Minutes per stage, indexed like the hypnogram: awake, REM, light, deep. */
export const stageMinutes: [number, number, number, number] = [0, 0, 0, 0]
for (const stage of hypnogram) stageMinutes[stage as 0 | 1 | 2 | 3] += 5
