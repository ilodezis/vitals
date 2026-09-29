import { queryOptions, useQuery } from '@tanstack/react-query'
import { api } from '@/api/client'
import type { GeneticsView } from './types'

export const defaultGeneticsView: GeneticsView = {
  variants: [],
  count: 0,
  empty: true,
}

export const geneticsQuery = queryOptions({
  queryKey: ['genetics'],
  queryFn: async (): Promise<GeneticsView> => {
    const { data, error } = await api.GET('/api/v1/genetics')
    if (error || data === undefined) throw new Error('Genetics data could not be read')
    return data as unknown as GeneticsView
  },
  staleTime: 60_000,
})

export function useGeneticsView(): GeneticsView {
  const { data } = useQuery(geneticsQuery)
  return data ?? defaultGeneticsView
}
