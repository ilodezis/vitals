import type { QueryClient } from '@tanstack/react-query'
import { chartsQuery } from '@/features/charts/useChartsView'
import { geneticsQuery } from '@/features/genetics/useGeneticsView'
import { glp1Query } from '@/features/glp1/useGlp1View'
import { hrtQuery } from '@/features/hrt/useHrtView'
import { interactionsQuery } from '@/features/interactions/useInteractionsView'
import { labsQuery } from '@/features/labs/useLabsView'
import { moreQuery } from '@/features/more/useMoreView'
import { activitiesQuery, nightsQuery } from '@/features/recovery/listQueries'
import { recoveryQuery } from '@/features/recovery/useRecoveryView'
import { reportsQuery } from '@/features/reports/useReportsView'
import { settingsQuery } from '@/features/settings/useSettingsView'
import { shareQuery } from '@/features/share/useShareView'
import { signalsQuery } from '@/features/signals/useSignalsView'
import { skincareQuery } from '@/features/skincare/useSkincareView'
import { supplementsQuery } from '@/features/supplements/useSupplementsView'
import { timelineQuery } from '@/features/timeline/useTimelineView'
import { measuresQuery } from '@/features/weight/measuresQuery'
import { weightQuery } from '@/features/weight/useWeightView'
import { workoutsQuery } from '@/features/workouts/workoutsQuery'

/** How many reads are in flight at once while warming: the app is open and in use, and the server is one box. */
const WARM_PARALLEL = 2

/** Run the jobs with at most `parallel` in flight. A failed one is skipped: the screen reads it again
 *  when it is opened and shows the failure itself. */
export async function runWarm(jobs: readonly (() => Promise<unknown>)[], parallel = WARM_PARALLEL): Promise<void> {
  const queue = [...jobs]
  const lane = async () => {
    for (let job = queue.shift(); job !== undefined; job = queue.shift()) {
      await job().catch(() => undefined)
    }
  }
  await Promise.all(Array.from({ length: Math.min(parallel, queue.length) }, lane))
}

/** The screens' reads, most visited first. */
const screenReads = (client: QueryClient): (() => Promise<unknown>)[] => [
  () => client.prefetchQuery(recoveryQuery),
  () => client.prefetchQuery(workoutsQuery),
  () => client.prefetchQuery(weightQuery),
  () => client.prefetchQuery(glp1Query),
  () => client.prefetchQuery(supplementsQuery),
  () => client.prefetchQuery(labsQuery),
  () => client.prefetchQuery(skincareQuery),
  () => client.prefetchQuery(hrtQuery),
  () => client.prefetchQuery(measuresQuery),
  () => client.prefetchQuery(nightsQuery),
  () => client.prefetchQuery(activitiesQuery),
  () => client.prefetchQuery(timelineQuery()),
  () => client.prefetchQuery(signalsQuery),
  () => client.prefetchQuery(chartsQuery),
  () => client.prefetchQuery(reportsQuery),
  () => client.prefetchQuery(interactionsQuery),
  () => client.prefetchQuery(geneticsQuery),
  () => client.prefetchQuery(shareQuery),
  () => client.prefetchQuery(moreQuery),
  () => client.prefetchQuery(settingsQuery),
]

let warmed = false

/** Once the app is open and idle, read every screen's data in the background so the first visit to a
 *  screen opens filled in, the way a return visit does. Once per page load. */
export function warmScreens(client: QueryClient): void {
  if (warmed) return
  warmed = true
  const start = () => void runWarm(screenReads(client))
  if (typeof requestIdleCallback === 'function') requestIdleCallback(start, { timeout: 4000 })
  else setTimeout(start, 2000)
}
