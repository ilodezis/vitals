export type WeightSource = 'manual' | 'bia' | 'garmin'

/** `GET /api/v1/weight`: one request, everything the Weight screen draws. */
export interface WeightView {
  kg: number
  /** The 7-day average, and the change against a week earlier. */
  average7: number
  weekDeltaKg: number
  bodyFatPct: number
  /** The drug whose dose phases the chart shades. */
  drug: string
  /** Weighings and their 7-day trend, oldest first. */
  weighings: { date: string; kg: number }[]
  trend: { date: string; kg: number }[]
  /** Dose phases the chart shades behind the line. */
  dosePhases: { from: string; to: string; label: string }[]
  history: WeightHistoryRow[]
  pace: {
    perWeekKg: number
    dose: { label: string; sinceIso: string; days: number; deltaKg: number }
    goal: { targetKg: number; weeks: number }
  }
  lastScan: { device: string; dateIso: string; rows: { label: string; value: string; unit: string }[] }
}

export interface WeightHistoryRow {
  date: string
  time: string
  kg: number
  source: WeightSource
  /** A Garmin row a manual or scan reading of the same day has taken over. */
  superseded?: boolean
  supersededBy?: string | null
  note?: string
}
