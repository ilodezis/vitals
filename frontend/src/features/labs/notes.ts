import { statusOf, type LabMarker, type LabStatus } from './types'

/** What a marker's history says, as the facts a sentence is built from: where it started, where it
 *  is, which way it went, and whether the latest result is still outside the range. */
export interface MarkerTrend {
  first: number
  last: number
  direction: 'up' | 'down'
  status: LabStatus
  /** Outside the range and moving toward it. */
  improving: boolean
}

export function markerTrend(m: Pick<LabMarker, 'history' | 'value' | 'lo' | 'hi'>): MarkerTrend {
  const first = m.history[0]?.value ?? m.value
  const last = m.history[m.history.length - 1]?.value ?? m.value
  const direction = last > first ? 'up' : 'down'
  const status = statusOf(m)
  const improving = (status === 'low' && direction === 'up') || (status === 'high' && direction === 'down')
  return { first, last, direction, status, improving }
}

/** The reference range as one line: "30–100". */
export function rangeText(m: Pick<LabMarker, 'lo' | 'hi' | 'decimals'>, format: (v: number, digits: number) => string): string {
  return `${format(m.lo, m.decimals)}–${format(m.hi, m.decimals)}`
}
