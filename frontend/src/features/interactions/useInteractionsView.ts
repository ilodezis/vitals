import { queryOptions, useSuspenseQuery } from '@tanstack/react-query'
import { api, ok } from '@/api/client'
import type { InteractionsView } from './types'

export const interactionsQuery = queryOptions({
  queryKey: ['interactions'],
  queryFn: async (): Promise<InteractionsView> => (await ok(api.GET('/api/v1/interactions'))) as unknown as InteractionsView,
  staleTime: 60_000,
})

/** `GET /api/v1/interactions`. A failed read is the screen's error state, not an empty screen: the throw goes
 *  to the boundary around the screen. */
export const useInteractionsView = (): InteractionsView => useSuspenseQuery(interactionsQuery).data
