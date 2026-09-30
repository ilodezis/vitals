export type NormKey = 'sleep' | 'hrv' | 'rhr' | 'stress' | 'steps' | 'bb'

/** Where the resting pulse stands against its corridor; empty when there is no reading. */
export type RhrNote = '' | 'normal' | 'upper' | 'above' | 'below'

/** The corridor for one metric, and which way is better. */
export interface Norm {
  lo: number
  hi: number
  better: 1 | -1
  /** A code — "", "ms" or "bpm" — that the screen prints in its language. */
  unit: string
}

/** One day of the table. A metric the watch did not record is `null`. */
export interface NightDay {
  dateIso: string
  sleep: number | null
  hrv: number | null
  rhr: number | null
  stress: number | null
  steps: number | null
  bb: number | null
}

/** `GET /api/v1/recovery`. What the watch has not reported is `null`: the screen prints a dash. */
export interface RecoveryView {
  /** Garmin is connected; without it there is nothing to sync. */
  isConfigured: boolean
  headline: {
    sleepScore: number | null
    sleepMinutes: number | null
    hrv: number | null
    hrvNightsBelow: number
    rhr: number | null
    rhrNote: RhrNote
    bodyBatteryFrom: number | null
    bodyBatteryTo: number | null
  }
  night: {
    dateIso: string
    /** Lights out and wake-up, "HH:MM"; null when the night has no bedtime recorded. */
    start: string | null
    end: string | null
    /** Sleep stages in 5-minute blocks: 0 awake, 1 REM, 2 light, 3 deep. */
    stages: number[]
    /** Minutes per stage, the same order; null when the night carries no breakdown. */
    stageMinutes: [number, number, number, number] | null
  } | null
  norms: Partial<Record<NormKey, Norm>>
  /** How many days the corridors were computed from; 0 while there is too little history. */
  normsDays: number
  /** How many days of history a corridor takes. */
  normsMinDays: number
  /** The "against your norm" rows: the latest value and how wide the bar is drawn. */
  bars: { key: 'sleep' | 'hrv' | 'rhr' | 'stress'; min: number; max: number; value: number | null; unit: string }[]
  days: NightDay[]
}
