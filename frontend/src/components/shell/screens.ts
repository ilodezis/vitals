import { lazy, type ComponentType } from 'react'
import type { ScreenId } from './nav'
import { wait } from '@/lib/motion'

/** Each built screen is its own chunk. The loaders are called ahead of a tap (a hover, a
 *  route's preload) so the screen is already here when the motion starts. */
const loaders: Partial<Record<ScreenId, () => Promise<{ default: ComponentType }>>> = {
  today: () => import('@/features/today/TodayScreen'),
  weight: () => import('@/features/weight/WeightScreen'),
  measures: () => import('@/features/weight/WeightMeasuresScreen'),
  recovery: () => import('@/features/recovery/RecoveryScreen'),
  sleep: () => import('@/features/recovery/SleepNightScreen'),
  nights: () => import('@/features/recovery/NightsListScreen'),
  activities: () => import('@/features/recovery/ActivitiesScreen'),
  workouts: () => import('@/features/workouts/WorkoutsScreen'),
  nutrition: () => import('@/features/nutrition/NutritionScreen'),
  glp1: () => import('@/features/glp1/Glp1Screen'),
  labs: () => import('@/features/labs/LabsScreen'),
  hrt: () => import('@/features/hrt/HrtScreen'),
  genetics: () => import('@/features/genetics/GeneticsScreen'),
  supplements: () => import('@/features/supplements/SupplementsScreen'),
  skincare: () => import('@/features/skincare/SkincareScreen'),
  interactions: () => import('@/features/interactions/InteractionsScreen'),
  signals: () => import('@/features/signals/SignalsScreen'),
  timeline: () => import('@/features/timeline/TimelineScreen'),
  reports: () => import('@/features/reports/ReportsScreen'),
  charts: () => import('@/features/charts/ChartsScreen'),
  share: () => import('@/features/share/ShareScreen'),
  more: () => import('@/features/more/MoreScreen'),
  settings: () => import('@/features/settings/SettingsScreen'),
}

const placeholder = () => import('@/features/placeholder/PlaceholderScreen')

/** The screens whose code has arrived, as components. */
const loaded = new Map<ScreenId, ComponentType>()

/** Fetch a screen's code without drawing it. Cheap to call again: modules load once. */
export function preloadScreen(id: ScreenId): Promise<unknown> {
  return (loaders[id] ?? placeholder)().then((mod) => {
    loaded.set(id, mod.default)
    return mod
  })
}

const components = new Map<ScreenId, ComponentType>()

/** The component that draws a screen; screens not built yet share one placeholder.
 *
 *  A screen whose code is already here is drawn as it is. `lazy` would still hold its first render
 *  back for a tick and show the empty fallback, and the screen's motion would start on that empty
 *  frame; only a screen asked for before its code arrived (a pasted link, the first paint) goes
 *  through `lazy`. The choice is made once per screen so a mounted screen never swaps its type. */
export function screenComponent(id: ScreenId): ComponentType {
  let component = components.get(id)
  if (component === undefined) {
    component = loaded.get(id) ?? lazy(loaders[id] ?? placeholder)
    components.set(id, component)
  }
  return component
}

/** How long a tap waits for a screen's data, once its code is here, before the screen opens without it. */
const DATA_WAIT_MS = 250

/** Everything a screen needs to open filled in: its code and its reads (`ensureQueryData` calls the
 *  route has already started). Data already on the device, even an old copy, is taken as it is and
 *  refreshed behind the screen; a slow read does not hold the tap past `DATA_WAIT_MS` — the screen
 *  opens and fills in when it arrives. */
export async function openScreen(id: ScreenId, ...reads: Promise<unknown>[]): Promise<void> {
  const settled = Promise.allSettled(reads)
  await preloadScreen(id)
  await Promise.race([settled, wait(DATA_WAIT_MS)])
}
