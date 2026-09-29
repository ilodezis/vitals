import { queryOptions, useQuery } from '@tanstack/react-query'
import { api } from '@/api/client'
import type { ReportsView } from './types'

export const defaultReportsView: ReportsView = {
  activeGoals: [],
  closedGoals: [],
  activeGoalsCount: 0,
  closedGoalsCount: 0,
  latestDigest: null,
  digestHistory: [],
  digestsCount: 0,
  latestBrief: null,
  goalDomains: ['weight', 'labs', 'garmin', 'nutrition', 'workouts'],
  llmConfigured: false,
  channelConfigured: false,
  today: new Date().toISOString().slice(0, 10),
}

export const reportsQuery = queryOptions({
  queryKey: ['reports'],
  queryFn: async (): Promise<ReportsView> => {
    const { data, error } = await api.GET('/api/v1/reports')
    if (error || data === undefined) throw new Error('Reports data could not be read')
    return data as unknown as ReportsView
  },
  staleTime: 60_000,
})

export function useReportsView(): ReportsView {
  const { data } = useQuery(reportsQuery)
  return data ?? defaultReportsView
}
