import { queryOptions, useSuspenseQuery } from '@tanstack/react-query'
import { api, ok } from '@/api/client'
import type { HrtView } from './types'

export const hrtQuery = queryOptions({
  queryKey: ['hrt'],
  queryFn: async (): Promise<HrtView> => (await ok(api.GET('/api/v1/hrt'))) as unknown as HrtView,
  staleTime: 60_000,
})

/** `GET /api/v1/hrt`. A failed read is the screen's error state, not an empty screen: the throw goes
 *  to the boundary around the screen. */
export const useHrtView = (): HrtView => useSuspenseQuery(hrtQuery).data
