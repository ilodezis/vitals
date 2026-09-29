/** A value's place on a scale, in percent, clamped to the scale. */
export function percentOf(value: number, min: number, max: number): number {
  return Math.min(100, Math.max(0, ((value - min) / (max - min)) * 100))
}

export interface RangeBarLayout {
  /** The user's corridor (or the lab's reference range) as a band; null for a single line. */
  ref: { left: number; width: number } | null
  /** Where the value sits. */
  point: number
  /** From "was" to "is": the stretch and where the hollow marker of the earlier value stands. */
  move: { left: number; width: number; from: number } | null
}

export function rangeBarLayout(o: {
  value: number
  /** The corridor; left out (or null) for a metric that has none. */
  lo?: number | null
  hi?: number | null
  min: number
  max: number
  prev?: number
}): RangeBarLayout {
  const { value, lo, hi, min, max, prev } = o
  const ref =
    lo === undefined || lo === null || hi === undefined || hi === null || lo === hi
      ? null
      : { left: percentOf(lo, min, max), width: percentOf(hi, min, max) - percentOf(lo, min, max) }
  const point = percentOf(value, min, max)
  let move: RangeBarLayout['move'] = null
  if (prev !== undefined) {
    const from = percentOf(prev, min, max)
    move = { left: Math.min(from, point), width: Math.abs(point - from), from }
  }
  return { ref, point, move }
}

/** Was it a change in the right direction? `better` is +1 when higher is better. */
export function changeTone(from: number, to: number, better: 1 | -1): 'good' | 'bad' | '' {
  const delta = to - from
  if (delta === 0) return ''
  return Math.sign(delta) * better > 0 ? 'good' : 'bad'
}

/** The scale a dumbbell row is drawn on: everything it shows (both weeks, the corridor) with a
 *  margin around it — 40% of what it spans, and never less than 2% of its own magnitude, so a
 *  weight that moved 0.8 kg still reads as small against the scale rather than filling it. */
export function rangeAxis(values: readonly number[], corridor?: { lo: number; hi: number } | null): { min: number; max: number } {
  const points = corridor ? [...values, corridor.lo, corridor.hi] : [...values]
  const lowest = Math.min(...points)
  const highest = Math.max(...points)
  const pad = Math.max(0.4 * (highest - lowest), 0.02 * Math.abs((lowest + highest) / 2), 1)
  return { min: lowest - pad, max: highest + pad }
}
