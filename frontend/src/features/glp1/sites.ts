import { daysBetween } from '@/lib/dates'
import type { Injection, SiteId } from './types'

/** Where each site is drawn on the body outline (150 × 190). */
export const SITE_POSITION: Record<SiteId, readonly [number, number]> = {
  shoulder_left: [44, 64],
  shoulder_right: [106, 64],
  abdomen_left: [64, 104],
  abdomen_right: [86, 104],
  thigh_left: [62, 150],
  thigh_right: [88, 150],
}

export const SITE_IDS = Object.keys(SITE_POSITION) as SiteId[]

export type SiteMark =
  /** The one used least recently — where the next one goes. */
  | { kind: 'next' }
  /** Used in the last three days. */
  | { kind: 'recent' }
  /** Older: the dimmer, the longer ago. `opacity` is the dot's fill opacity. */
  | { kind: 'older'; opacity: number }

export interface SiteUsage {
  site: SiteId
  /** The most recent injection at the site; null if never. */
  last: Date | null
  mark: SiteMark
}

const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v))

/** Rotation at a glance: sites ordered from least to most recently used (never-used first), the
 *  first of them marked as the next one, the rest by how fresh they are. `injections` need not be
 *  ordered. */
export function siteUsage(injections: readonly Pick<Injection, 'site' | 'dateIso'>[], today: Date, parse: (iso: string) => Date): SiteUsage[] {
  const last = new Map<SiteId, Date>()
  for (const inj of injections) {
    if (inj.site === null) continue
    const d = parse(inj.dateIso)
    const seen = last.get(inj.site)
    if (seen === undefined || d > seen) last.set(inj.site, d)
  }
  const ordered = [...SITE_IDS].sort((a, b) => (last.get(a)?.getTime() ?? 0) - (last.get(b)?.getTime() ?? 0))
  return ordered.map((site, i): SiteUsage => {
    const date = last.get(site) ?? null
    if (i === 0) return { site, last: date, mark: { kind: 'next' } }
    const age = date === null ? 99 : daysBetween(date, today)
    if (age <= 3) return { site, last: date, mark: { kind: 'recent' } }
    return { site, last: date, mark: { kind: 'older', opacity: clamp(0.7 - age / 40, 0.15, 0.6) } }
  })
}
