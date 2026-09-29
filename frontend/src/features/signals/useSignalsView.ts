import { queryOptions, useQuery } from '@tanstack/react-query'
import { api } from '@/api/client'
import type { SignalsView } from './types'

export const defaultSignalsView: SignalsView = {
  signals: [],
  frequency: [],
  kinds: ['state', 'symptom', 'exposure'],
  misparseCount: 0,
  totalCount: 0,
  keysCount: 0,
}

export const signalsQuery = queryOptions({
  queryKey: ['signals'],
  queryFn: async (): Promise<SignalsView> => {
    const { data, error } = await api.GET('/api/v1/signals')
    if (error || data === undefined) throw new Error('Signals data could not be read')
    return data as unknown as SignalsView
  },
  staleTime: 60_000,
})

export function useSignalsView(): SignalsView {
  const { data } = useQuery(signalsQuery)
  return data ?? defaultSignalsView
}
