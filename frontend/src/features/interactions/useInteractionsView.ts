import { queryOptions, useQuery } from '@tanstack/react-query'
import { api } from '@/api/client'
import type { InteractionsView } from './types'

export const defaultInteractionsView: InteractionsView = {
  rules: [],
  orderedCategories: [],
  firingIds: [],
  allDomains: ['weight', 'glp1', 'workouts', 'garmin', 'labs', 'skincare', 'supplements', 'genetics', 'nutrition'],
  totalCount: 0,
  firingCount: 0,
}

export const interactionsQuery = queryOptions({
  queryKey: ['interactions'],
  queryFn: async (): Promise<InteractionsView> => {
    const { data, error } = await api.GET('/api/v1/interactions')
    if (error || data === undefined) throw new Error('Interactions data could not be read')
    return data as unknown as InteractionsView
  },
  staleTime: 60_000,
})

export function useInteractionsView(): InteractionsView {
  const { data } = useQuery(interactionsQuery)
  return data ?? defaultInteractionsView
}
