import { queryOptions, useSuspenseQuery } from '@tanstack/react-query'
import { api, ok } from '@/api/client'
import type { SupplementsView } from './types'

export const supplementsQuery = queryOptions({
  queryKey: ['supplements'],
  queryFn: async (): Promise<SupplementsView> => (await ok(api.GET('/api/v1/supplements'))) as unknown as SupplementsView,
  staleTime: 60_000,
})

/** `GET /api/v1/supplements`. A failed read is the screen's error state, not an empty screen: the throw goes
 *  to the boundary around the screen. */
export const useSupplementsView = (): SupplementsView => useSuspenseQuery(supplementsQuery).data
