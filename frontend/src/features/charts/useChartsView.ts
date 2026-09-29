import { queryOptions, useQuery } from '@tanstack/react-query'
import { api } from '@/api/client'
import type { ChartsView } from './types'

export const defaultChartsView: ChartsView = {
  charts: [],
  catalog: {},
  count: 0,
  empty: true,
}

export const chartsQuery = queryOptions({
  queryKey: ['charts'],
  queryFn: async (): Promise<ChartsView> => {
    const { data, error } = await api.GET('/api/v1/charts')
    if (error || data === undefined) throw new Error('Charts data could not be read')
    return data as unknown as ChartsView
  },
  staleTime: 60_000,
})

export function useChartsView(): ChartsView {
  const { data } = useQuery(chartsQuery)
  return data ?? defaultChartsView
}
