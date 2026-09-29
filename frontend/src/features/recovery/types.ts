export type NormKey = 'sleep' | 'hrv' | 'rhr' | 'stress' | 'steps' | 'bb'

/** The user's own corridor for one metric (60 days of their data), and which way is better. */
export interface Norm {
  lo: number
  hi: number
  better: 1 | -1
  unit: string
}

export interface NightDay {
  dateIso: string
  sleep: number
  hrv: number
  rhr: number
  stress: number
  steps: number
  bb: number
}

/** `GET /api/v1/recovery`. */
export interface RecoveryView {
  headline: {
    sleepScore: number
    sleepMinutes: number
    hrv: number
    hrvNightsBelow: number
    rhr: number
    /** Where the resting pulse stands against the norm, as a ready phrase. */
    rhrNote: string
    bodyBatteryFrom: number
    bodyBatteryTo: number
  }
  night: {
    dateIso: string
    /** Lights out and wake-up, "HH:MM". */
    start: string
    end: string
    /** Sleep stages in 5-minute blocks: 0 awake, 1 REM, 2 light, 3 deep. */
    stages: number[]
    /** Minutes per stage, the same order. */
    stageMinutes: [number, number, number, number]
  }
  norms: Record<NormKey, Norm>
  /** The four "against your norm" rows and how wide their bar is drawn. */
  bars: { key: 'sleep' | 'hrv' | 'rhr' | 'stress'; min: number; max: number }[]
  days: NightDay[]
}
