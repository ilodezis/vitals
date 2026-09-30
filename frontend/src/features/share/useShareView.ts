import { queryOptions, useSuspenseQuery } from '@tanstack/react-query'
import { api, ok } from '@/api/client'
import type { ShareView } from './types'

export const shareQuery = queryOptions({
  queryKey: ['share'],
  queryFn: async (): Promise<ShareView> => (await ok(api.GET('/api/v1/share'))) as unknown as ShareView,
  staleTime: 60_000,
})

/** `GET /api/v1/share`. A failed read is the screen's error state, not an empty screen: the throw goes
 *  to the boundary around the screen. */
export const useShareView = (): ShareView => useSuspenseQuery(shareQuery).data
