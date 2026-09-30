import { queryOptions, useSuspenseQuery } from '@tanstack/react-query'
import { api, ok } from '@/api/client'
import type { SignalsView } from './types'

export const signalsQuery = queryOptions({
  queryKey: ['signals'],
  queryFn: async (): Promise<SignalsView> => (await ok(api.GET('/api/v1/signals'))) as unknown as SignalsView,
  staleTime: 60_000,
})

/** `GET /api/v1/signals`. A failed read is the screen's error state, not an empty screen: the throw goes
 *  to the boundary around the screen. */
export const useSignalsView = (): SignalsView => useSuspenseQuery(signalsQuery).data
