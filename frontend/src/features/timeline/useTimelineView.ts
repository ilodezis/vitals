import { queryOptions, useQuery } from '@tanstack/react-query'
import { api } from '@/api/client'
import type { TimelineView } from './types'

export const defaultTimelineView: TimelineView = {
  events: [],
  manualCount: 0,
  totalCount: 0,
  domains: ['weight', 'glp1', 'workouts', 'garmin', 'labs', 'skincare', 'supplements', 'timeline'],
  kinds: ['life_event', 'protocol_change', 'injury', 'trip', 'note'],
  today: new Date().toISOString().slice(0, 10),
}

export const timelineQuery = (domain?: string) =>
  queryOptions({
    queryKey: ['timeline', domain ?? 'all'],
    queryFn: async (): Promise<TimelineView> => {
      const { data, error } = await api.GET('/api/v1/timeline', {
        params: { query: { domain: domain === 'all' ? undefined : domain } },
      })
      if (error || data === undefined) throw new Error('Timeline data could not be read')
      return data as unknown as TimelineView
    },
    staleTime: 60_000,
  })

export function useTimelineView(domain?: string): TimelineView {
  const { data } = useQuery(timelineQuery(domain))
  return data ?? defaultTimelineView
}
