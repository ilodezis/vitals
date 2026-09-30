import { queryOptions, useSuspenseQuery } from '@tanstack/react-query'
import { api, ok } from '@/api/client'
import type { TimelineView } from './types'

export const timelineQuery = (domain?: string) =>
  queryOptions({
    queryKey: ['timeline', domain ?? 'all'],
    queryFn: async (): Promise<TimelineView> =>
      (await ok(api.GET('/api/v1/timeline', { params: { query: { domain: domain === undefined || domain === 'all' ? undefined : domain } } }))) as unknown as TimelineView,
    staleTime: 60_000,
  })

/** `GET /api/v1/timeline` for one domain (or all of them). Pass a deferred filter value: the
 *  screen then keeps the previous list on screen while the next one is read. */
export const useTimelineView = (domain?: string): TimelineView => useSuspenseQuery(timelineQuery(domain)).data
