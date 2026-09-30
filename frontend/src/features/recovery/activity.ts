import type { components } from '@/api/schema'

type ActivityItem = components['schemas']['ActivityItem']

/** Zone colours, cool to hot: Z1 is recovery, Z5 is the red line. */
export const ZONE_COLOR = ['var(--cool)', 'var(--good)', 'var(--accent)', 'var(--warn)', 'var(--bad)'] as const

/** Anything beyond the summary to open: training effect, climb, power, zones or laps. */
export const hasDetail = (a: ActivityItem): boolean =>
  a.hr_zones.length > 0 ||
  a.splits.length > 1 ||
  a.training_effect_aerobic != null ||
  a.training_effect_anaerobic != null ||
  a.elevation_gain_meters != null ||
  a.avg_power != null

/** 305 → "5:05": a lap's time. */
export const lapTime = (seconds: number): string => {
  const s = Math.round(seconds)
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}
