/* System alerts as the screens read them: a domain's active ones, and hiding them.

   The list of a screen lives under that screen's own query key (`['weight', 'alerts']`), so
   whatever refreshes the screen after a write refreshes its alerts too. */

import { queryOptions, useMutation, useQueryClient } from '@tanstack/react-query'
import { api, ok } from '@/api/client'
import type { components } from '@/api/schema'
import { toast } from '@/components/controls/toast'
import { useT } from '@/i18n/useT'
import type { AlertTone } from './Alert'

export type SystemAlert = components['schemas']['SystemAlertItem']

const TONES: readonly string[] = ['note', 'info', 'warn', 'block']

/** The rung of the ladder an alert stands on; a severity the screen does not know is a heads-up. */
export const toneOf = (severity: string): AlertTone => (TONES.includes(severity) ? (severity as AlertTone) : 'info')

/** The alert behind a line of Today's "needs attention": the same domain, rung and words.
 *  A line that is not an alert (an observation about the night) has none and cannot be hidden. */
export function alertIdOf(item: { domain: string | null; severity: string; message: string }, alerts: readonly SystemAlert[]): number | undefined {
  return alerts.find((a) => a.domain === item.domain && a.severity === item.severity && a.message === item.message)?.id
}

/** Active alerts of one domain, or of all of them. `scope` is the query key of the screen
 *  that shows them. */
export const alertsQuery = (scope: string, domain?: string) =>
  queryOptions({
    queryKey: [scope, 'alerts'],
    queryFn: async (): Promise<SystemAlert[]> =>
      (await ok(api.GET('/api/v1/alerts', { params: { query: domain === undefined ? {} : { domain } } }))).alerts ?? [],
  })

/** Hide one alert, or every alert of a domain. The alert leaves the list at once; if the
 *  server refuses, the list is read again and says what is really there. */
export function useHideAlerts(scope: string) {
  const { t } = useT()
  const queryClient = useQueryClient()
  const key = alertsQuery(scope).queryKey

  const drop = async (gone: (alert: SystemAlert) => boolean) => {
    await queryClient.cancelQueries({ queryKey: key })
    queryClient.setQueryData(key, (list) => list?.filter((a) => !gone(a)))
  }
  const failed = () => toast(t('app.action_failed'), { icon: 'warn' })
  // Today lists every domain's alerts, so it is read again whichever screen hid one.
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: [scope] })
    if (scope !== 'today') void queryClient.invalidateQueries({ queryKey: ['today'] })
  }

  const hide = useMutation({
    mutationFn: (id: number) => ok(api.POST('/api/v1/alerts/{alert_id}/resolve', { params: { path: { alert_id: id } } })),
    onMutate: (id) => drop((a) => a.id === id),
    onError: failed,
    onSettled: refresh,
  })
  const hideAll = useMutation({
    mutationFn: (domain: string) => ok(api.POST('/api/v1/alerts/resolve-all', { params: { query: { domain } } })),
    onMutate: (domain) => drop((a) => a.domain === domain),
    onError: failed,
    onSettled: refresh,
  })

  return { hide: (id: number) => hide.mutate(id), hideAll: (domain: string) => hideAll.mutate(domain) }
}
