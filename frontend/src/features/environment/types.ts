/* What the environment API says, as the screens read it. The generated schema is the contract; the
   shapes below are the same with every absent field spelled `null`, so no screen has to tell
   "missing" from "empty" (see `environmentApi.ts`, where the one conversion happens). */

import type { components } from '@/api/schema'

type Schemas = components['schemas']

export type EnvThresholds = Schemas['Thresholds']
export type EnvSettings = Schemas['EnvSettings']
export type EnvSettingsPatch = Schemas['EnvSettingsPatch']
export type EnvStationCheck = Schemas['StationCheck']
export type EnvPoint = Schemas['Point']
export type EnvRange = Schemas['RangeStats']
export type StationStatus = Schemas['LiveStation']['status']
export type Co2Zone = Schemas['LiveNow']['co2_zone']
export type EnvResolution = Schemas['SeriesView']['resolution']
export type EnvWindow = Schemas['Window']

export interface EnvStation {
  status: StationStatus
  last_seen_at: string | null
  age_s: number | null
  rssi: number | null
  fw: string | null
}

export interface EnvNow {
  co2_ppm: number | null
  temperature_c: number | null
  humidity_pct: number | null
  lux: number | null
  co2_zone: Co2Zone
  co2_trend_ppm_per_h: number | null
}

export interface EnvLive {
  /** False when no station address is set at all; true with `status: 'never'` is a station that has not spoken yet. */
  configured: boolean
  station: EnvStation
  now: EnvNow
  thresholds: EnvThresholds
}

export interface EnvSeries {
  points: EnvPoint[]
  /** The resolution the points really are in, which can be coarser than the one asked for. */
  resolution: EnvResolution
  coverage_pct: number
  thresholds: EnvThresholds
  window: EnvWindow
}

export type EnvSummary = Schemas['PeriodSummary']

/** A night: the summary of its window, and the minute series inside it. */
export interface EnvPeriod {
  summary: EnvSummary
  series: EnvPoint[]
  thresholds: EnvThresholds
}
