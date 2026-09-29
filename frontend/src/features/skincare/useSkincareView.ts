import { queryOptions, useQuery } from '@tanstack/react-query'
import { api } from '@/api/client'
import type { SkincareView } from './types'

export const defaultSkincareView: SkincareView = {
  products: [],
  activeCount: 0,
  totalCount: 0,
  todayLog: null,
  logs: [],
  observations: [],
  rules: [],
  alerts: [],
  today: new Date().toISOString().slice(0, 10),
}

export const skincareQuery = queryOptions({
  queryKey: ['skincare'],
  queryFn: async (): Promise<SkincareView> => {
    const { data, error } = await api.GET('/api/v1/skincare')
    if (error || data === undefined) throw new Error('Skincare data could not be read')
    return data as unknown as SkincareView
  },
  staleTime: 60_000,
})

export function useSkincareView(): SkincareView {
  const { data } = useQuery(skincareQuery)
  return data ?? defaultSkincareView
}
