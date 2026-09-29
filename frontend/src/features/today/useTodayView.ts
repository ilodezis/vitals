import { queryOptions, useSuspenseQuery } from '@tanstack/react-query'
import { api } from '@/api/client'
import type { TodayView } from './types'

/** `GET /api/v1/today`: the whole screen in one request. It is what the device keeps, so the
 *  app opens on the last day it saw while the fresh one is on its way. */
export const todayQuery = queryOptions({
  queryKey: ['today'],
  queryFn: async (): Promise<TodayView> => {
    const { data } = await api.GET('/api/v1/today')
    if (data === undefined) throw new Error('Today could not be read')
    return data
  },
  // The screen the app opens on: older than a minute is asked again on the next visit.
  staleTime: 60_000,
})

export const useTodayView = (): TodayView => useSuspenseQuery(todayQuery).data
