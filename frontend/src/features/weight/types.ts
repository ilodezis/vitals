export type WeightSource = 'manual' | 'bia' | 'garmin'

/** `GET /api/v1/weight`: one request, everything the Weight screen draws. A value the server
 *  does not have is `null`, never a stand-in. */
export interface WeightView {
  kg: number | null
  /** The 7-day average, and the change against a week earlier. */
  average7: number | null
  weekDeltaKg: number | null
  bodyFatPct: number | null
  /** Where the body-fat figure comes from: the scan's device, or "Navy" for the tape formula. */
  bodyFatSource: string | null
  /** The drug whose dose phases the chart shades. */
  drug: string
  /** Weighings and their 7-day trend, oldest first. */
  weighings: { date: string; kg: number }[]
  trend: { date: string; kg: number }[]
  /** Dose phases the chart shades behind the line; `to` is `null` for the one still running. */
  dosePhases: { from: string; to: string | null; drug: string; doseMg: number }[]
  history: WeightHistoryRow[]
  pace: {
    perWeekKg: number | null
    dose: { drug: string | null; doseMg: number | null; sinceIso: string; days: number; deltaKg: number | null } | null
    goal: { targetKg: number; weeks: number | null } | null
  }
  lastScan: { device: string | null; dateIso: string; rows: { label: string; value: number; unit: string }[] } | null
}

export interface WeightHistoryRow {
  id: number
  date: string
  time: string
  kg: number
  source: WeightSource
  /** A Garmin row a manual or scan reading of the same day has taken over. */
  superseded?: boolean
  supersededBy?: string | null
  note?: string
}
