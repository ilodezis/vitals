import { queryOptions } from '@tanstack/react-query'
import { api, ok } from '@/api/client'
import type { components } from '@/api/schema'
import type { EnvLive, EnvPeriod, EnvResolution, EnvSeries, EnvSettings, EnvSettingsPatch, EnvStationCheck } from './types'

type Schemas = components['schemas']

/** How often the live reading is asked for while its screen is in view. */
export const LIVE_REFETCH_MS = 10_000
/** The curves move slower than the figure: once a minute is enough to keep them current. */
export const SERIES_REFETCH_MS = 60_000

export const WINDOWS = [6, 24, 72] as const
export type WindowHours = (typeof WINDOWS)[number]

/** Minute readings up to two days; beyond that the server answers from its hourly roll-up. */
export const resolutionFor = (hours: number): EnvResolution => (hours > 48 ? 'hour' : 'minute')

/** The API leaves out what it does not have; the screens read `null`. */
export function liveOf(raw: Schemas['LiveView']): EnvLive {
  const { station, now } = raw
  return {
    configured: raw.configured,
    station: {
      status: station.status,
      last_seen_at: station.last_seen_at ?? null,
      age_s: station.age_s ?? null,
      rssi: station.rssi ?? null,
      fw: station.fw ?? null,
    },
    now: {
      co2_ppm: now.co2_ppm ?? null,
      temperature_c: now.temperature_c ?? null,
      humidity_pct: now.humidity_pct ?? null,
      lux: now.lux ?? null,
      co2_zone: now.co2_zone,
      co2_trend_ppm_per_h: now.co2_trend_ppm_per_h ?? null,
    },
    thresholds: raw.thresholds,
  }
}

export const seriesOf = (raw: Schemas['SeriesView']): EnvSeries => ({ ...raw, points: raw.points ?? [] })

export const periodOf = (raw: Schemas['PeriodView']): EnvPeriod => ({ ...raw, series: raw.series ?? [] })

export const readLive = async (): Promise<EnvLive> => liveOf(await ok(api.GET('/api/v1/environment/live')))

export const readSeries = async (hours: number): Promise<EnvSeries> =>
  seriesOf(await ok(api.GET('/api/v1/environment/series', { params: { query: { hours, resolution: resolutionFor(hours) } } })))

export const readNight = async (date: string): Promise<EnvPeriod> =>
  periodOf(await ok(api.GET('/api/v1/environment/night/{on_date}', { params: { path: { on_date: date } } })))

export const readSettings = (): Promise<EnvSettings> => ok(api.GET('/api/v1/environment/settings'))

export const writeSettings = (patch: EnvSettingsPatch): Promise<EnvSettings> => ok(api.PUT('/api/v1/environment/settings', { body: patch }))

export const checkStation = (): Promise<EnvStationCheck> => ok(api.POST('/api/v1/environment/station/check'))

export const environmentLiveQuery = queryOptions({
  queryKey: ['environment', 'live'],
  queryFn: readLive,
  staleTime: 5_000,
})

export const environmentSeriesQuery = (hours: number) =>
  queryOptions({
    queryKey: ['environment', 'series', hours],
    queryFn: () => readSeries(hours),
    staleTime: 30_000,
  })

export const environmentNightQuery = (date: string) =>
  queryOptions({
    queryKey: ['environment', 'night', date],
    queryFn: () => readNight(date),
    staleTime: 60_000,
  })

export const environmentSettingsQuery = queryOptions({
  queryKey: ['environment', 'settings'],
  queryFn: readSettings,
  staleTime: 30_000,
})
