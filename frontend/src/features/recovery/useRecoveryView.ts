import { queryOptions, useSuspenseQuery } from '@tanstack/react-query'
import { api, ok } from '@/api/client'
import type { components } from '@/api/schema'
import type { Norm, NormKey, RecoveryView, RhrNote } from './types'

type RawRecoveryView = components['schemas']['RecoveryView']

const NORM_KEYS: readonly NormKey[] = ['sleep', 'hrv', 'rhr', 'stress', 'steps', 'bb']
const BAR_KEYS = ['sleep', 'hrv', 'rhr', 'stress'] as const
const RHR_NOTES: readonly RhrNote[] = ['', 'normal', 'upper', 'above', 'below']

/** The API's answer as the screen reads it: what the watch did not report stays `null`. */
export function toRecoveryView(data: RawRecoveryView): RecoveryView {
  const hl = data.headline
  const n = data.night ?? null
  const norms: RecoveryView['norms'] = {}
  for (const key of NORM_KEYS) {
    const raw = data.norms[key]
    if (raw === undefined) continue
    const norm: Norm = {
      lo: raw.lo,
      hi: raw.hi,
      better: raw.better < 0 ? -1 : 1,
      unit: raw.unit,
    }
    norms[key] = norm
  }
  const [awake, rem, light, deep] = n?.stage_minutes ?? []
  const a = data.activity
  return {
    isConfigured: data.is_configured,
    dateIso: data.date,
    isToday: data.is_today,
    lastSync: data.last_sync ?? null,
    advice: data.advice ?? null,
    activity: {
      steps: a.steps ?? null,
      stress: a.stress ?? null,
      intensityModerate: a.intensity_moderate ?? null,
      intensityVigorous: a.intensity_vigorous ?? null,
      activeCalories: a.active_calories ?? null,
    },
    intraday: {
      stress: data.intraday.stress,
      bodyBattery: data.intraday.body_battery,
      heartRate: data.intraday.heart_rate,
    },
    headline: {
      sleepScore: hl.sleep_score ?? null,
      sleepMinutes: hl.sleep_minutes ?? null,
      hrv: hl.hrv ?? null,
      hrvNightsBelow: hl.hrv_nights_below,
      rhr: hl.rhr ?? null,
      rhrNote: RHR_NOTES.find((r) => r === hl.rhr_note) ?? '',
      bodyBatteryFrom: hl.body_battery_from ?? null,
      bodyBatteryTo: hl.body_battery_to ?? null,
    },
    night:
      n === null
        ? null
        : {
            dateIso: n.date,
            start: n.start === '' ? null : n.start,
            end: n.end === '' ? null : n.end,
            stages: n.stages,
            stageMinutes:
              awake === undefined || rem === undefined || light === undefined || deep === undefined ? null : [awake, rem, light, deep],
          },
    norms,
    normsDays: data.norms_days,
    normsMinDays: data.norms_min_days,
    bars: data.bars.flatMap((b) => {
      const key = BAR_KEYS.find((k) => k === b.key)
      return key === undefined ? [] : [{ key, min: b.min, max: b.max, value: b.value ?? null, unit: b.unit }]
    }),
    days: data.days.map((d) => ({
      dateIso: d.date,
      sleep: d.sleep ?? null,
      hrv: d.hrv ?? null,
      rhr: d.rhr ?? null,
      stress: d.stress ?? null,
      steps: d.steps ?? null,
      bb: d.bb ?? null,
      awake: d.awake_count ?? null,
    })),
  }
}

export const recoveryQuery = queryOptions({
  queryKey: ['recovery'],
  queryFn: async (): Promise<RecoveryView> => toRecoveryView(await ok(api.GET('/api/v1/recovery'))),
  staleTime: 60_000,
})

/** `GET /api/v1/recovery`. A failed read is the screen's error state, not a screen of zeros. */
export const useRecoveryView = (): RecoveryView => useSuspenseQuery(recoveryQuery).data
