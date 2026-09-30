import { queryOptions, useQuery } from '@tanstack/react-query'
import { api } from '@/api/client'
import { toIsoDate } from '@/lib/dates'
import type { Glp1View } from './types'

const todayIso = () => toIsoDate(new Date())

const EMPTY_GLP1: Glp1View = {
  drug: 'Семаглутид',
  doseMg: 0,
  sinceIso: todayIso(),
  dayOnDose: 0,
  cycle: {
    lastIso: null,
    nextIso: todayIso(),
    daysToNext: 0,
    overdue: false,
    unscheduled: true,
  },
  dosePhases: [],
  trend: [],
  summary: '',
  siteLabels: {
    shoulder_left: 'Плечо Л',
    shoulder_right: 'Плечо П',
    abdomen_left: 'Живот Л',
    abdomen_right: 'Живот П',
    thigh_left: 'Бедро Л',
    thigh_right: 'Бедро П',
  },
  injections: [],
  sideEffects: [],
}

export const glp1Query = queryOptions({
  queryKey: ['glp1'],
  queryFn: async (): Promise<Glp1View> => {
    const { data, error } = await api.GET('/api/v1/glp1')
    if (error || data === undefined) throw new Error('GLP-1 data could not be read')
    return data as unknown as Glp1View
  },
  staleTime: 60_000,
})

export function useGlp1View(): Glp1View {
  const { data } = useQuery(glp1Query)
  return data ?? EMPTY_GLP1
}
