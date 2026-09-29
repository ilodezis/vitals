import { queryOptions, useQuery } from '@tanstack/react-query'
import { api } from '@/api/client'
import type { SupplementsView } from './types'

export const defaultSupplementsView: SupplementsView = {
  groups: [],
  active: [],
  archived: [],
  activeCount: 0,
  totalCount: 0,
}

export const supplementsQuery = queryOptions({
  queryKey: ['supplements'],
  queryFn: async (): Promise<SupplementsView> => {
    const { data, error } = await api.GET('/api/v1/supplements')
    if (error || data === undefined) throw new Error('Supplements data could not be read')
    return data as unknown as SupplementsView
  },
  staleTime: 60_000,
})

export function useSupplementsView(): SupplementsView {
  const { data } = useQuery(supplementsQuery)
  return data ?? defaultSupplementsView
}
