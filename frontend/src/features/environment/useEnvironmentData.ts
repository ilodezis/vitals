import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { sessionQuery } from '@/app/session'
import { environmentNightQuery, environmentSeriesQuery, environmentSettingsQuery, SERIES_REFETCH_MS } from './environmentApi'

/** Reads of the environment that belong to a part of a screen: when one fails, that part says so
 *  and the rest of the screen stays. */

/** The curves of the last `hours`, refreshed once a minute while in view. The window that was
 *  on screen stays until the next one has arrived. */
export function useEnvironmentSeries(hours: number, inView: boolean) {
  return useQuery({
    ...environmentSeriesQuery(hours),
    placeholderData: keepPreviousData,
    refetchInterval: inView ? SERIES_REFETCH_MS : false,
    refetchIntervalInBackground: false,
  })
}

/** The night of `date`: the window from midnight to noon of the day it ends. */
export function useEnvironmentNight(date: string, enabled = true) {
  return useQuery({ ...environmentNightQuery(date), enabled })
}

export function useEnvironmentSettings() {
  return useQuery(environmentSettingsQuery)
}

/** Whether the environment module is on, as the session says. Off, or the session not read yet:
 *  nothing asks the API. */
export function useEnvironmentEnabled(): boolean {
  const { data } = useQuery({ ...sessionQuery, retry: false })
  return data?.enabled_modules.environment === true
}
