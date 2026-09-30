import { queryOptions, useSuspenseQuery } from '@tanstack/react-query'
import { api, ok } from '@/api/client'
import type { LabsView } from './types'

export const labsQuery = queryOptions({
  queryKey: ['labs'],
  queryFn: async (): Promise<LabsView> => (await ok(api.GET('/api/v1/labs'))) as unknown as LabsView,
  staleTime: 60_000,
})

/** `GET /api/v1/labs`. A failed read is the screen's error state, not an empty screen: the throw goes
 *  to the boundary around the screen. */
export const useLabsView = (): LabsView => useSuspenseQuery(labsQuery).data
