/* The navigation model: which screens exist, where each lives, and how the session's
   module list becomes the rail, the bottom bar and the More screen. The server decides
   which sections are on (`session.nav.items`, in rail order); this file only knows how
   each one looks and where the redesigned app keeps it. */

import type { IconName } from '@/components/icons/Icon'
import type { components } from '@/api/schema'

export type SessionView = components['schemas']['SessionView']
export type NavItem = components['schemas']['NavItem']

export type ScreenId =
  | 'today' | 'weight' | 'measures' | 'recovery' | 'sleep' | 'nights' | 'activities'
  | 'workouts' | 'nutrition' | 'glp1' | 'hrt' | 'labs' | 'genetics'
  | 'supplements' | 'skincare' | 'interactions' | 'signals'
  | 'timeline' | 'reports' | 'charts' | 'share' | 'more' | 'settings'

/** Where each screen lives. A screen with a `$param` is matched by prefix. */
export const SCREEN_PATH: Record<ScreenId, string> = {
  today: '/today',
  weight: '/weight',
  measures: '/weight/measures',
  recovery: '/recovery',
  sleep: '/recovery/sleep',
  nights: '/recovery/nights',
  activities: '/recovery/activities',
  workouts: '/workouts',
  nutrition: '/nutrition',
  glp1: '/glp1',
  hrt: '/hrt',
  labs: '/labs',
  genetics: '/genetics',
  supplements: '/supplements',
  skincare: '/skincare',
  interactions: '/interactions',
  signals: '/signals',
  timeline: '/timeline',
  reports: '/reports',
  charts: '/charts',
  share: '/share',
  more: '/more',
  settings: '/settings',
}

/** The i18n key of each screen's name: the rail, the top bar's title and the back label. */
export const SCREEN_TITLE_KEY: Record<ScreenId, string> = {
  today: 'nav.today',
  weight: 'nav.weight',
  measures: 'app.title.measures',
  recovery: 'nav.garmin',
  sleep: 'app.title.sleep',
  nights: 'app.title.nights',
  activities: 'app.title.activities',
  workouts: 'nav.hevy',
  nutrition: 'nav.nutrition',
  glp1: 'nav.glp1',
  hrt: 'nav.hrt',
  labs: 'nav.labs',
  genetics: 'nav.genetics',
  supplements: 'nav.supplements',
  skincare: 'nav.skincare',
  interactions: 'nav.interactions',
  signals: 'nav.signals',
  timeline: 'nav.timeline',
  reports: 'nav.reports',
  charts: 'nav.charts',
  share: 'app.nav.share',
  more: 'nav.more',
  settings: 'nav.settings',
}

/** Screens that live one level below a section: the rail and the bar keep the parent lit. */
const PARENT: Partial<Record<ScreenId, ScreenId>> = {
  measures: 'weight',
  sleep: 'recovery',
  nights: 'recovery',
  activities: 'recovery',
}

/** A module key from the server → the screen it opens and the icon it wears. */
export const MODULE_SCREEN: Record<string, { screen: ScreenId; icon: IconName }> = {
  weight: { screen: 'weight', icon: 'scale' },
  garmin: { screen: 'recovery', icon: 'pulse' },
  hevy: { screen: 'workouts', icon: 'dumbbell' },
  nutrition: { screen: 'nutrition', icon: 'bowl' },
  glp1: { screen: 'glp1', icon: 'syringe' },
  hrt: { screen: 'hrt', icon: 'hrt' },
  labs: { screen: 'labs', icon: 'flask' },
  genetics: { screen: 'genetics', icon: 'dna' },
  supplements: { screen: 'supplements', icon: 'pill' },
  skincare: { screen: 'skincare', icon: 'skincare' },
  interactions: { screen: 'interactions', icon: 'interactions' },
  signals: { screen: 'signals', icon: 'signals' },
  timeline: { screen: 'timeline', icon: 'timeline' },
  reports: { screen: 'reports', icon: 'doc' },
  charts: { screen: 'charts', icon: 'chart' },
}

/** Screens that are built. The rest open a placeholder until their run lands. */
export const BUILT_SCREENS: ReadonlySet<ScreenId> = new Set<ScreenId>([
  'today', 'weight', 'recovery', 'glp1', 'labs', 'hrt', 'genetics', 'more',
])

export const navScreen = (id: ScreenId): ScreenId => PARENT[id] ?? id

export function screenForPath(pathname: string): ScreenId | null {
  const path = pathname.length > 1 ? pathname.replace(/\/+$/, '') : pathname
  let best: ScreenId | null = null
  for (const [id, base] of Object.entries(SCREEN_PATH) as [ScreenId, string][]) {
    if (path === base || path.startsWith(`${base}/`)) {
      if (best === null || base.length > SCREEN_PATH[best].length) best = id
    }
  }
  return best
}

export interface NavSection {
  key: string
  screen: ScreenId
  icon: IconName
}

export interface NavRubric {
  id: string
  sections: NavSection[]
}

/** The session's flat, rail-ordered list → rubrics in rail order, unknown modules skipped. */
export function rubricsOf(items: readonly NavItem[]): NavRubric[] {
  const out: NavRubric[] = []
  for (const item of items) {
    const meta = MODULE_SCREEN[item.key]
    if (meta === undefined) continue
    let rubric = out.find((r) => r.id === item.rubric)
    if (rubric === undefined) {
      rubric = { id: item.rubric, sections: [] }
      out.push(rubric)
    }
    rubric.sections.push({ key: item.key, screen: meta.screen, icon: meta.icon })
  }
  return out
}

/** A bottom-bar tab: today, a rubric (its first section is where it goes), or More. */
export interface BarTab {
  id: string
  kind: 'today' | 'rubric' | 'more'
  icon: IconName
  /** Where a tap goes. */
  screen: ScreenId
  /** The tab that stays lit for a screen. */
  rubric?: string
}

const RUBRIC_ICON: Record<string, IconName> = {
  health: 'heart',
  markers: 'drop',
  lifestyle: 'pill',
  journal: 'doc',
}

/** Today · two rubrics · More, with the amber "+" between the rubrics. The rubrics are the
 *  first two the server left with anything in them, in rail order. */
export function barTabs(rubrics: readonly NavRubric[]): { left: BarTab[]; right: BarTab[] } {
  const picked = rubrics.filter((r) => r.sections.length > 0).slice(0, 2)
  const asTab = (r: NavRubric): BarTab => ({
    id: r.id,
    kind: 'rubric',
    icon: RUBRIC_ICON[r.id] ?? 'grid',
    screen: (r.sections[0] as NavSection).screen,
    rubric: r.id,
  })
  const today: BarTab = { id: 'today', kind: 'today', icon: 'today', screen: 'today' }
  const more: BarTab = { id: 'more', kind: 'more', icon: 'grid', screen: 'more' }
  const [first, second] = picked
  return {
    left: first === undefined ? [today] : [today, asTab(first)],
    right: second === undefined ? [more] : [asTab(second), more],
  }
}

/** Which bar tab a root screen belongs to. */
export function tabOf(id: ScreenId, rubrics: readonly NavRubric[], tabs: readonly BarTab[]): string {
  if (id === 'today') return 'today'
  if (id === 'more') return 'more'
  const rubric = rubrics.find((r) => r.sections.some((s) => s.screen === navScreen(id)))
  const tab = tabs.find((t) => t.kind === 'rubric' && t.rubric === rubric?.id)
  return tab?.id ?? 'more'
}

/** The rubric a screen sits in — the masthead's section tabs. */
export function rubricOfScreen(id: ScreenId, rubrics: readonly NavRubric[]): NavRubric | undefined {
  return rubrics.find((r) => r.sections.some((s) => s.screen === navScreen(id)))
}
