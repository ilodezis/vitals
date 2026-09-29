import { queryOptions, useSuspenseQuery } from '@tanstack/react-query'
import { api } from '@/api/client'
import type { SessionView } from '@/components/shell/nav'

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
})

export const useSession = (): SessionView => useSuspenseQuery(sessionQuery).data
