import { api } from '@/api/client'
import type { components } from '@/api/schema'

type WeightMeasuresView = components['schemas']['WeightMeasuresView']

/** `GET /api/v1/weight/measures`. Its own module: the log sheet reads it too, and importing it from
 *  the screen would pull the whole screen into the startup bundle. */
export const measuresQuery = {
  queryKey: ['weight', 'measures'],
  queryFn: async (): Promise<WeightMeasuresView> => {
    const { data, error } = await api.GET('/api/v1/weight/measures')
    if (error !== undefined || data === undefined) throw new Error('Measures could not be read')
    return data
  },
}
