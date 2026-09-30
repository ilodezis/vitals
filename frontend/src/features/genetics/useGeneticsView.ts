import { queryOptions, useSuspenseQuery } from '@tanstack/react-query'
import { api, ok } from '@/api/client'
import type { GeneticsView } from './types'

export const geneticsQuery = queryOptions({
  queryKey: ['genetics'],
  queryFn: async (): Promise<GeneticsView> => (await ok(api.GET('/api/v1/genetics'))) as unknown as GeneticsView,
  staleTime: 60_000,
})

/** `GET /api/v1/genetics`. A failed read is the screen's error state, not an empty screen: the throw goes
 *  to the boundary around the screen. */
export const useGeneticsView = (): GeneticsView => useSuspenseQuery(geneticsQuery).data
