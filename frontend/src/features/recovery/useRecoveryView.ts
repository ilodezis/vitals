import { queryOptions, useSuspenseQuery } from '@tanstack/react-query'
import { api } from '@/api/client'
import { recoveryFixture } from '@/fixtures/recovery'
import type { RecoveryView } from './types'

export const recoveryQuery = queryOptions({
  queryKey: ['recovery'],
  queryFn: async (): Promise<RecoveryView> => {
    const { data } = await api.GET('/api/v1/recovery')
    if (!data) return recoveryFixture
    const hl = data.headline
    const n = data.night
    return {
      headline: {
        sleepScore: hl.sleep_score ?? recoveryFixture.headline.sleepScore,
        sleepMinutes: hl.sleep_minutes ?? recoveryFixture.headline.sleepMinutes,
        hrv: hl.hrv ?? recoveryFixture.headline.hrv,
        hrvNightsBelow: hl.hrv_nights_below ?? 0,
        rhr: hl.rhr ?? recoveryFixture.headline.rhr,
        rhrNote: hl.rhr_note || 'норма',
        bodyBatteryFrom: hl.body_battery_from ?? 0,
        bodyBatteryTo: hl.body_battery_to ?? 100,
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
        : recoveryFixture.night,
      norms: (data.norms as unknown as RecoveryView['norms']) || recoveryFixture.norms,
      bars: (data.bars as unknown as RecoveryView['bars']) || recoveryFixture.bars,
      days: (data.days ?? []).length > 0
        ? (data.days ?? []).map((d) => ({
            dateIso: d.date,
            sleep: d.sleep ?? 0,
            hrv: d.hrv ?? 0,
            rhr: d.rhr ?? 0,
            stress: d.stress ?? 0,
            steps: d.steps ?? 0,
            bb: d.bb ?? 0,
          }))
        : recoveryFixture.days,
    }
  },
  staleTime: 60_000,
})

export function useRecoveryView(): RecoveryView {
  try {
    return useSuspenseQuery(recoveryQuery).data
  } catch {
    return recoveryFixture
  }
}
