import { api } from '@/api/client'
import type { components } from '@/api/schema'

type WorkoutsView = components['schemas']['WorkoutsView']

/** `GET /api/v1/workouts`. Its own module so the route can read it ahead of the screen. */
export const workoutsQuery = {
  queryKey: ['workouts'],
  queryFn: async (): Promise<WorkoutsView> => {
    const { data, error } = await api.GET('/api/v1/workouts')
    if (error !== undefined || data === undefined) throw new Error('Workouts could not be read')
    return data
  },
}
