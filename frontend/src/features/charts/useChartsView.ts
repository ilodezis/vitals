import { queryOptions, useSuspenseQuery } from '@tanstack/react-query'
import { api, ok } from '@/api/client'
import type { ChartsView } from './types'

export const chartsQuery = queryOptions({
  queryKey: ['charts'],
  queryFn: async (): Promise<ChartsView> => (await ok(api.GET('/api/v1/charts'))) as unknown as ChartsView,
  staleTime: 60_000,
})

/** `GET /api/v1/charts`. A failed read is the screen's error state, not an empty screen: the throw goes
 *  to the boundary around the screen. */
export const useChartsView = (): ChartsView => useSuspenseQuery(chartsQuery).data
