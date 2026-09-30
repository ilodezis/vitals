import { queryOptions, useSuspenseQuery } from '@tanstack/react-query'
import { api, ok } from '@/api/client'
import type { SkincareView } from './types'

export const skincareQuery = queryOptions({
  queryKey: ['skincare'],
  queryFn: async (): Promise<SkincareView> => (await ok(api.GET('/api/v1/skincare'))) as unknown as SkincareView,
  staleTime: 60_000,
})

/** `GET /api/v1/skincare`. A failed read is the screen's error state, not an empty screen: the throw goes
 *  to the boundary around the screen. */
export const useSkincareView = (): SkincareView => useSuspenseQuery(skincareQuery).data
