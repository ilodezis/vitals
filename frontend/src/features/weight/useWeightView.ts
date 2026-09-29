import { queryOptions, useSuspenseQuery } from '@tanstack/react-query'
import { api } from '@/api/client'
import { weightFixture } from '@/fixtures/weight'
import type { WeightView } from './types'

export const weightQuery = queryOptions({
  queryKey: ['weight'],
  queryFn: async (): Promise<WeightView> => {
    const { data } = await api.GET('/api/v1/weight')
    if (!data) return weightFixture
    return {
      kg: data.latest_kg ?? weightFixture.kg,
      average7: data.average7 ?? 0,
      weekDeltaKg: data.week_delta_kg ?? 0,
      bodyFatPct: data.body_fat_pct ?? 0,
      drug: data.drug || 'GLP-1',
      weighings: (data.weighings ?? []).map((p) => ({ date: p.date, kg: p.kg })),
      trend: (data.trend ?? []).map((p) => ({ date: p.date, kg: p.kg })),
      dosePhases: (data.dose_phases ?? []).map((p) => ({
        from: p.from_date,
        to: p.to_date ?? p.from_date,
        label: p.label,
      })),
      history: (data.history ?? []).map((h) => ({
        date: h.date,
        time: h.time,
        kg: h.weight_kg,
        source: h.source as 'manual' | 'bia' | 'garmin',
        superseded: h.superseded,
        note: h.note ?? undefined,
      })),
      pace: {
        perWeekKg: data.pace?.per_week_kg ?? 0,
        dose: {
          label: data.pace?.dose?.label ?? 'Dose',
          sinceIso: data.pace?.dose?.since_date ?? data.latest_date ?? new Date().toISOString().slice(0, 10),
          days: data.pace?.dose?.days ?? 0,
          deltaKg: data.pace?.dose?.delta_kg ?? 0,
        },
        goal: {
          targetKg: data.pace?.goal?.target_kg ?? 80,
          weeks: data.pace?.goal?.weeks ?? 0,
        },
      },
      lastScan: data.last_scan
        ? {
            device: data.last_scan.device || 'InBody',
            dateIso: data.last_scan.date,
            rows: (data.last_scan.rows ?? []).map((r) => ({
              label: r.label,
              value: String(r.value),
              unit: r.unit ?? '',
            })),
          }
        : weightFixture.lastScan,
    }
  },
  staleTime: 60_000,
})

export function useWeightView(): WeightView {
  try {
    return useSuspenseQuery(weightQuery).data
  } catch {
    return weightFixture
  }
}
