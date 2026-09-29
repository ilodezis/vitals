import { queryOptions, useQuery } from '@tanstack/react-query'
import { api } from '@/api/client'
import type { HrtView } from './types'

export const defaultHrtView: HrtView = {
  cycle: null,
  doses: [],
  sideEffects: [],
  templates: [],
  planned: [],
  release: [],
  catalog: 0,
  compounds: [],
  siteLabels: {},
  siteCounts: {},
  last: null,
}

export const hrtQuery = queryOptions({
  queryKey: ['hrt'],
  queryFn: async (): Promise<HrtView> => {
    const { data, error } = await api.GET('/api/v1/hrt')
    if (error || data === undefined) throw new Error('HRT data could not be read')
    return data as unknown as HrtView
  },
  staleTime: 60_000,
})

export function useHrtView(): HrtView {
  const { data } = useQuery(hrtQuery)
  return data ?? defaultHrtView
}
