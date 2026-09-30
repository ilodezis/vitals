import { queryOptions, useSuspenseQuery } from '@tanstack/react-query'
import { api, ok } from '@/api/client'
import type { components } from '@/api/schema'

export type SettingsView = components['schemas']['SettingsView']

export const settingsQuery = queryOptions({
  queryKey: ['settings'],
  queryFn: async (): Promise<SettingsView> => ok(api.GET('/api/v1/settings')),
  staleTime: 30_000,
})

/** `GET /api/v1/settings`. There is no stand-in profile: a form drawn from guesses could be saved
 *  over the real one, so a failed read is the screen's error state. */
export const useSettingsView = (): SettingsView => useSuspenseQuery(settingsQuery).data
