import { queryOptions, useSuspenseQuery } from '@tanstack/react-query'
import { api } from '@/api/client'
import type { components } from '@/api/schema'
import type { WeightSource, WeightView } from './types'

type RawWeightView = components['schemas']['WeightView']

/** The API's answer as the screen reads it. What the server does not have stays `null` — the
 *  screen prints a dash or leaves the row out; nothing is filled in with a likely number. */
export function toWeightView(data: RawWeightView): WeightView {
  const dose = data.pace.dose ?? null
  const goal = data.pace.goal ?? null
  const scan = data.last_scan ?? null
  return {
    kg: data.latest_kg ?? null,
    average7: data.average7 ?? null,
    weekDeltaKg: data.week_delta_kg ?? null,
    bodyFatPct: data.body_fat_pct ?? null,
    bodyFatSource: data.body_fat_source ?? null,
    drug: data.drug,
    weighings: (data.weighings ?? []).map((p) => ({ date: p.date, kg: p.kg })),
    trend: (data.trend ?? []).map((p) => ({ date: p.date, kg: p.kg })),
    dosePhases: (data.dose_phases ?? []).map((p) => ({
      from: p.from_date,
      to: p.to_date ?? null,
      drug: p.drug,
      doseMg: p.dose_mg,
    })),
    history: (data.history ?? []).map((h) => ({
      id: h.id,
      date: h.date,
      time: h.time ?? '',
      kg: h.weight_kg,
      source: h.source as WeightSource,
      superseded: h.superseded,
      supersededBy: h.superseded_by ?? null,
      note: h.note ?? undefined,
    })),
    pace: {
      perWeekKg: data.pace.per_week_kg ?? null,
      dose:
        dose === null
          ? null
          : {
              drug: dose.drug ?? null,
              doseMg: dose.dose_mg ?? null,
              sinceIso: dose.since_date,
              days: dose.days,
              deltaKg: dose.delta_kg ?? null,
            },
      goal: goal === null ? null : { targetKg: goal.target_kg, weeks: goal.weeks ?? null },
    },
    lastScan:
      scan === null
        ? null
        : {
            device: scan.device ?? null,
            dateIso: scan.date,
            rows: (scan.rows ?? []).map((r) => ({ label: r.label, value: r.value, unit: r.unit ?? '' })),
          },
  }
}

export const weightQuery = queryOptions({
  queryKey: ['weight'],
  queryFn: async (): Promise<WeightView> => {
    const { data, error } = await api.GET('/api/v1/weight')
    if (error !== undefined || data === undefined) throw new Error('Weight could not be read')
    return toWeightView(data)
  },
  staleTime: 60_000,
})

/** `GET /api/v1/weight`. A request that fails is the screen's error state, not a screen of
 *  zeros: the throw goes to the boundary around the screen. */
export const useWeightView = (): WeightView => useSuspenseQuery(weightQuery).data
