import { queryOptions, useQuery } from '@tanstack/react-query'
import { api } from '@/api/client'
import { labsFixture } from '@/fixtures/labs'
import type { LabsView } from './types'

export const labsQuery = queryOptions({
  queryKey: ['labs'],
  queryFn: async (): Promise<LabsView> => {
    const { data, error } = await api.GET('/api/v1/labs')
    if (error || data === undefined) throw new Error('Labs could not be read')
    return data as unknown as LabsView
  },
  staleTime: 60_000,
})

export function useLabsView(): LabsView {
  const { data } = useQuery(labsQuery)
  return data ?? labsFixture
}
