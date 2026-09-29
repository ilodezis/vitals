import { lazy, type ComponentType } from 'react'
import type { ScreenId } from './nav'

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
  more: () => import('@/features/more/MoreScreen'),
}

const placeholder = () => import('@/features/placeholder/PlaceholderScreen')

/** Fetch a screen's code without drawing it. Cheap to call again: modules load once. */
export function preloadScreen(id: ScreenId): Promise<unknown> {
  return (loaders[id] ?? placeholder)()
}

const components = new Map<ScreenId, ComponentType>()

/** The component that draws a screen; screens not built yet share one placeholder. */
export function screenComponent(id: ScreenId): ComponentType {
  let component = components.get(id)
  if (component === undefined) {
    const load = loaders[id] ?? placeholder
    component = lazy(load)
    components.set(id, component)
  }
  return component
}
