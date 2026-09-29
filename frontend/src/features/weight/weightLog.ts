/* Saving a weight — the write behind the stepper on Today and in the log sheet.

   The number is on the screen before the server has answered. If the conflict engine holds it back
   (a `ConflictError`, with the rules it tripped), the service refuses it (an `InvalidError`) or the
   network drops it, the screen goes back to what it had; if it is saved, the server is asked again
   for the day and for the rail, so what stays is what the server made of it. */

import { type MutationOptions, type QueryClient, MutationObserver, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/api/client'
import { applyLoggedWeight } from '@/features/today/optimistic'
import { todayQuery } from '@/features/today/useTodayView'
import type { TodayView } from '@/features/today/types'
import { toIsoDate } from '@/lib/dates'

interface Vars {
  kg: number
  /** The day the server calls today: the client's own clock may be in another one. */
  date: string
  override: boolean
}

interface Saved {
  id: number
  /** False when the day already held this very reading: there is nothing to take back. */
  created: boolean
}

interface Context {
  before: TodayView | undefined
}

/** Everything a weigh-in changes on the server: the day, and the rail's weight card. */
const refetchAfterWeight = (queryClient: QueryClient) =>
  Promise.all([
    queryClient.invalidateQueries({ queryKey: todayQuery.queryKey }),
    queryClient.invalidateQueries({ queryKey: ['weight'] }),
    queryClient.invalidateQueries({ queryKey: ['session'] }),
  ])

function logWeightMutation(queryClient: QueryClient): MutationOptions<Saved, Error, Vars, Context> {
  return {
    mutationFn: async ({ kg, date, override }) => {
      const { data } = await api.POST('/api/v1/weight/logs', { body: { date, weight_kg: kg, override } })
      if (data === undefined) throw new Error('The weight was not saved')
      return data
    },
    onMutate: async ({ kg }) => {
      // A refetch already on its way would land on top of the number just drawn.
      await queryClient.cancelQueries({ queryKey: todayQuery.queryKey })
      const before = queryClient.getQueryData(todayQuery.queryKey)
      if (before !== undefined) queryClient.setQueryData(todayQuery.queryKey, applyLoggedWeight(before, kg))
      return { before }
    },
    onError: (_error, _vars, context) => {
      if (context?.before !== undefined) queryClient.setQueryData(todayQuery.queryKey, context.before)
    },
    onSettled: () => refetchAfterWeight(queryClient),
  }
}

/** Save a weight as today's reading. Rejects with `ConflictError` when it is held back (repeat it
 *  with `override: true` to keep it anyway) and with `InvalidError` when the service refuses it.
 *  Resolves with an `undo` unless the day already held this reading. */
export async function saveWeight(
  queryClient: QueryClient,
  kg: number,
  { override }: { override: boolean },
): Promise<{ undo: (() => Promise<void>) | undefined }> {
  const date = queryClient.getQueryData(todayQuery.queryKey)?.date ?? toIsoDate(new Date())
  const saved = await new MutationObserver(queryClient, logWeightMutation(queryClient)).mutate({ kg, date, override })
  if (!saved.created) return { undo: undefined }
  return {
    undo: async () => {
      await api.DELETE('/api/v1/weight/logs/{log_id}', { params: { path: { log_id: saved.id } } })
      await refetchAfterWeight(queryClient)
    },
  }
}

/** The weight the steppers start from and the screens quote: the latest reading the day knows of,
 *  which follows a save the moment it is drawn. `kg` is `null` before there has ever been one;
 *  `today` is the day the server calls today. */
export function useLatestWeight(): { kg: number | null; date: string | null; today: string | null } {
  const { data } = useQuery(todayQuery)
  return { kg: data?.latest_weight?.kg ?? null, date: data?.latest_weight?.date ?? null, today: data?.date ?? null }
}

export function useSaveWeight(): (kg: number, options: { override: boolean }) => ReturnType<typeof saveWeight> {
  const queryClient = useQueryClient()
  return (kg, options) => saveWeight(queryClient, kg, options)
}
