import { queryOptions, useSuspenseQuery } from '@tanstack/react-query'
import { api, ok } from '@/api/client'
import type { ReportsView } from './types'

export const reportsQuery = queryOptions({
  queryKey: ['reports'],
  queryFn: async (): Promise<ReportsView> => (await ok(api.GET('/api/v1/reports'))) as unknown as ReportsView,
  staleTime: 60_000,
})

/** `GET /api/v1/reports`. A failed read is the screen's error state, not an empty screen: the throw goes
 *  to the boundary around the screen. */
export const useReportsView = (): ReportsView => useSuspenseQuery(reportsQuery).data
