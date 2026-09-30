import { useMemo } from 'react'
import { queryOptions, useQuery, useSuspenseQuery } from '@tanstack/react-query'
import { api } from '@/api/client'
import type { SessionView } from '@/components/shell/nav'
import { parseIsoDate, toIsoDate } from '@/lib/dates'

/** `GET /api/v1/session`: who is signed in, the language, the module switches, the navigation
 *  built from them and the rail's status card. The root route loads it before anything draws. */
export const sessionQuery = queryOptions({
  queryKey: ['session'],
  queryFn: async (): Promise<SessionView> => {
    const { data } = await api.GET('/api/v1/session')
    if (data === undefined) throw new Error('The session could not be read')
    return data
  },
  // The shell is drawn from it on every screen; a switched module refreshes it explicitly.
  staleTime: 5 * 60_000,
  refetchOnWindowFocus: true,
  refetchOnMount: 'always',
})

export const useSession = (): SessionView => useSuspenseQuery(sessionQuery).data

/** Server-authoritative local date (`VITALS_TIMEZONE`) from `/api/v1/session`, with a safe
 *  local-calendar fallback for isolated component tests where session isn't prefetched. */
export const useToday = (): Date => {
  const { data } = useQuery({ ...sessionQuery, retry: false })
  return useMemo(() => {
    if (data?.today) return parseIsoDate(data.today)
    const now = new Date()
    return new Date(now.getFullYear(), now.getMonth(), now.getDate())
  }, [data?.today])
}

export const useTodayIso = (): string => {
  const { data } = useQuery({ ...sessionQuery, retry: false })
  return useMemo(() => data?.today ?? toIsoDate(new Date()), [data?.today])
}
