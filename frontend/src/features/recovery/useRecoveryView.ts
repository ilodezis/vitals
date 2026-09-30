import { queryOptions, useSuspenseQuery } from '@tanstack/react-query'
import { api } from '@/api/client'
import { toIsoDate } from '@/lib/dates'
import type { Norm, NormKey, RecoveryView } from './types'

const DEFAULT_NORMS: Record<NormKey, Norm> = {
  sleep: { lo: 75, hi: 85, better: 1, unit: '' },
  hrv: { lo: 48, hi: 62, better: 1, unit: 'мс' },
  rhr: { lo: 49, hi: 55, better: -1, unit: 'уд' },
  stress: { lo: 18, hi: 28, better: -1, unit: '' },
  steps: { lo: 8000, hi: 12000, better: 1, unit: '' },
  bb: { lo: 70, hi: 90, better: 1, unit: '' },
}

const DEFAULT_BARS: RecoveryView['bars'] = [
  { key: 'sleep', min: 40, max: 100 },
  { key: 'hrv', min: 35, max: 75 },
  { key: 'rhr', min: 40, max: 65 },
  { key: 'stress', min: 0, max: 60 },
]

const EMPTY_RECOVERY: RecoveryView = {
  headline: {
    sleepScore: 0,
    sleepMinutes: 0,
    hrv: 0,
    hrvNightsBelow: 0,
    rhr: 0,
    rhrNote: 'норма',
    bodyBatteryFrom: 0,
    bodyBatteryTo: 0,
  },
  night: {
    dateIso: toIsoDate(new Date()),
    start: '23:00',
    end: '07:00',
    stages: [],
    stageMinutes: [0, 0, 0, 0],
  },
  norms: DEFAULT_NORMS,
  bars: DEFAULT_BARS,
  days: [],
}

export const recoveryQuery = queryOptions({
  queryKey: ['recovery'],
  queryFn: async (): Promise<RecoveryView> => {
    const { data } = await api.GET('/api/v1/recovery')
    if (!data) return EMPTY_RECOVERY
    const hl = data.headline
    const n = data.night
    return {
      headline: {
        sleepScore: hl.sleep_score ?? 0,
        sleepMinutes: hl.sleep_minutes ?? 0,
        hrv: hl.hrv ?? 0,
        hrvNightsBelow: hl.hrv_nights_below ?? 0,
        rhr: hl.rhr ?? 0,
        rhrNote: hl.rhr_note || 'норма',
        bodyBatteryFrom: hl.body_battery_from ?? 0,
        bodyBatteryTo: hl.body_battery_to ?? 0,
      },
      night: n
        ? {
            dateIso: n.date,
            start: n.start,
            end: n.end,
            stages: n.stages,
            stageMinutes: [
              n.stage_minutes[0] ?? 0,
              n.stage_minutes[1] ?? 0,
              n.stage_minutes[2] ?? 0,
              n.stage_minutes[3] ?? 0,
            ],
          }
        : {
            ...EMPTY_RECOVERY.night,
            dateIso: data.date ?? toIsoDate(new Date()),
          },
      norms: (data.norms as unknown as RecoveryView['norms']) || DEFAULT_NORMS,
      bars: (data.bars as unknown as RecoveryView['bars']) || DEFAULT_BARS,
      days: (data.days ?? []).map((d) => ({
        dateIso: d.date,
        sleep: d.sleep ?? 0,
        hrv: d.hrv ?? 0,
        rhr: d.rhr ?? 0,
        stress: d.stress ?? 0,
        steps: d.steps ?? 0,
        bb: d.bb ?? 0,
      })),
    }
  },
  staleTime: 60_000,
})

export function useRecoveryView(): RecoveryView {
  try {
    return useSuspenseQuery(recoveryQuery).data
  } catch {
    return EMPTY_RECOVERY
  }
}
