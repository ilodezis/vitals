import { useEffect, useRef } from 'react'
import { useSuspenseQuery } from '@tanstack/react-query'
import { environmentLiveQuery, LIVE_REFETCH_MS } from './environmentApi'

/** `GET /api/v1/environment/live`, kept current while the screen is in view. A tab in the
 *  background is not asked: the browser pauses the interval, and it catches up on return. The first
 *  read failing is the screen's error state; a later one failing keeps the last reading on screen. */
export function useEnvironmentLive(inView: boolean) {
  const query = useSuspenseQuery({
    ...environmentLiveQuery,
    refetchInterval: inView ? LIVE_REFETCH_MS : false,
    refetchIntervalInBackground: false,
  })
  // Coming back to the screen: the reading it kept is as old as the time away, not one poll old.
  const wasInView = useRef(inView)
  const { refetch } = query
  useEffect(() => {
    if (inView && !wasInView.current) void refetch()
    wasInView.current = inView
  }, [inView, refetch])
  return query
}
