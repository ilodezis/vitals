import { queryOptions, useQuery, useSuspenseQuery } from '@tanstack/react-query'
import { api, ok } from '@/api/client'
import type { components } from '@/api/schema'
import type { Glp1View, SiteId } from './types'

type RawGlp1View = components['schemas']['Glp1View']

const clampSeverity = (n: number): 1 | 2 | 3 | 4 | 5 => Math.min(5, Math.max(1, Math.round(n))) as 1 | 2 | 3 | 4 | 5

/** The API's answer as the screen reads it. */
export function toGlp1View(data: RawGlp1View): Glp1View {
  return {
    drug: data.drug ?? null,
    doseMg: data.doseMg ?? null,
    sinceIso: data.sinceIso ?? null,
    dayOnDose: data.dayOnDose ?? null,
    deltaOnDoseKg: data.deltaOnDoseKg ?? null,
    cycle: {
      lastIso: data.cycle.lastIso ?? null,
      nextIso: data.cycle.nextIso ?? null,
      daysToNext: data.cycle.daysToNext ?? null,
      overdue: data.cycle.overdue,
      unscheduled: data.cycle.unscheduled,
    },
    dosePhases: data.dosePhases.map((p) => ({ id: p.id ?? undefined, fromIso: p.fromIso, toIso: p.toIso, doseMg: p.doseMg, drug: p.drug ?? undefined, open: p.open })),
    trend: data.trend,
    siteLabels: data.siteLabels,
    injections: data.injections.map((i) => ({
      id: i.id ?? undefined,
      dateIso: i.dateIso,
      site: (i.site ?? null) as SiteId | null,
      doseMg: i.doseMg,
      drug: i.drug ?? undefined,
      note: i.note ?? undefined,
    })),
    sideEffects: data.sideEffects.map((e) => ({ id: e.id ?? undefined, dateIso: e.dateIso, name: e.name, severity: clampSeverity(e.severity) })),
  }
}

export const glp1Query = queryOptions({
  queryKey: ['glp1'],
  queryFn: async (): Promise<Glp1View> => toGlp1View(await ok(api.GET('/api/v1/glp1'))),
  staleTime: 60_000,
})

/** `GET /api/v1/glp1` for the screen: a failed read is the screen's error state. */
export const useGlp1View = (): Glp1View => useSuspenseQuery(glp1Query).data

/** The same data for what is always on screen (the log sheet): it never suspends, and is
 *  `undefined` until the read is in — or when it failed. */
export const useGlp1Snapshot = (): Glp1View | undefined => useQuery(glp1Query).data
