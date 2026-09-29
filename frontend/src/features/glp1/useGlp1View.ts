import { queryOptions, useQuery } from '@tanstack/react-query'
import { api } from '@/api/client'
import { glp1Fixture } from '@/fixtures/glp1'
import type { Glp1View } from './types'

export const glp1Query = queryOptions({
  queryKey: ['glp1'],
  queryFn: async (): Promise<Glp1View> => {
    const { data, error } = await api.GET('/api/v1/glp1')
    if (error || data === undefined) throw new Error('GLP-1 data could not be read')
    return data as unknown as Glp1View
  },
  staleTime: 60_000,
})

export function useGlp1View(): Glp1View {
  const { data } = useQuery(glp1Query)
  return data ?? glp1Fixture
}
