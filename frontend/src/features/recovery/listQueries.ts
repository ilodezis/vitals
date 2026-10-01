import { api, ok } from '@/api/client'
import type { components } from '@/api/schema'

type ActivitiesListView = components['schemas']['ActivitiesListView']
type NightsListView = components['schemas']['NightsListView']

/** The Garmin lists, in their own module so a route can read them ahead of the screen. */
export const activitiesQuery = {
  queryKey: ['recovery', 'activities'],
  queryFn: async (): Promise<ActivitiesListView> => ok(api.GET('/api/v1/recovery/activities', { params: { query: { limit: 30 } } })),
}

export const nightsQuery = {
  queryKey: ['recovery', 'nights'],
  queryFn: async (): Promise<NightsListView> => ok(api.GET('/api/v1/recovery/nights', { params: { query: { limit: 60 } } })),
}
