export type LabStatus = 'low' | 'ok' | 'high'

export interface LabMarker {
  id: string
  name: string
  /** The group's key, for the filter, and its name in the user's language. */
  groupKey: string
  group: string
  unit: string
  value: number
  /** The lab's reference range, and how wide the scale is drawn around it. */
  lo: number
  hi: number
  min: number
  max: number
  decimals: number
  /** Earlier results, oldest first; the last one is the latest draw. */
  history: { dateIso: string; value: number }[]
}

/** `GET /api/v1/labs`. */
export interface LabsView {
  collectedIso: string
  lab: string
  source: string
  markers: LabMarker[]
  /** Every marker of the catalog: its retest interval, its priority (1 is the highest) and a
   *  paused reminder. */
  catalog: { name: string; tier: number; retestIntervalDays?: number | null; deferUntil?: string | null }[]
}

export function statusOf(m: Pick<LabMarker, 'value' | 'lo' | 'hi'>): LabStatus {
  return m.value < m.lo ? 'low' : m.value > m.hi ? 'high' : 'ok'
}
