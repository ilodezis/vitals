import { queryOptions, useQuery } from '@tanstack/react-query'
import { api } from '@/api/client'
import type { ShareView } from './types'

export const defaultShareView: ShareView = {
  reports: [],
  availableDomains: ['weight', 'body_comp', 'labs', 'glp1', 'hrt', 'supplements', 'signals'],
  presets: {},
  periodChoices: [30, 90, 180, 365],
  expiryChoices: [7, 14, 30],
  defaultExpiry: 14,
  defaultStart: '',
  defaultEnd: '',
  today: new Date().toISOString().slice(0, 10),
}

export const shareQuery = queryOptions({
  queryKey: ['share'],
  queryFn: async (): Promise<ShareView> => {
    const { data, error } = await api.GET('/api/v1/share')
    if (error || data === undefined) throw new Error('Share data could not be read')
    return data as unknown as ShareView
  },
  staleTime: 60_000,
})

export function useShareView(): ShareView {
  const { data } = useQuery(shareQuery)
  return data ?? defaultShareView
}
