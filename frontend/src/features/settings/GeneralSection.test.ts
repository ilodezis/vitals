import { describe, expect, it } from 'vitest'
import { groupSettingsModules } from './GeneralSection'
import type { NavItem } from '@/components/shell/nav'

describe('groupSettingsModules', () => {
  const sampleNavItems: NavItem[] = [
    { key: 'weight', rubric: 'health', route: '/weight', eyebrow: '' },
    { key: 'recovery', rubric: 'health', route: '/recovery', eyebrow: '' },
    { key: 'workouts', rubric: 'health', route: '/workouts', eyebrow: '' },
    { key: 'nutrition', rubric: 'health', route: '/nutrition', eyebrow: '' },
    { key: 'glp1', rubric: 'health', route: '/glp1', eyebrow: '' },
    { key: 'hrt', rubric: 'health', route: '/hrt', eyebrow: '' },
    { key: 'labs', rubric: 'markers', route: '/labs', eyebrow: '' },
    { key: 'genetics', rubric: 'markers', route: '/genetics', eyebrow: '' },
    { key: 'supplements', rubric: 'lifestyle', route: '/supplements', eyebrow: '' },
    { key: 'skincare', rubric: 'lifestyle', route: '/skincare', eyebrow: '' },
    { key: 'interactions', rubric: 'journal', route: '/interactions', eyebrow: '' },
    { key: 'signals', rubric: 'journal', route: '/signals', eyebrow: '' },
    { key: 'timeline', rubric: 'journal', route: '/timeline', eyebrow: '' },
    { key: 'reports', rubric: 'journal', route: '/reports', eyebrow: '' },
    { key: 'charts', rubric: 'journal', route: '/charts', eyebrow: '' },
  ]

  it('groups modules dynamically by rubric from nav items', () => {
    const groups = groupSettingsModules(sampleNavItems, {})

    expect(groups.length).toBe(4)
    expect(groups.map((g) => g.rubric)).toEqual(['health', 'markers', 'lifestyle', 'journal'])
    expect(groups.map((g) => g.rubricKey)).toEqual([
      'masthead.rubric.health',
      'masthead.rubric.markers',
      'masthead.rubric.lifestyle',
      'masthead.rubric.journal',
    ])
  })

  it('places body_comp specifically into the health group with nav.body_comp title key', () => {
    const groups = groupSettingsModules(sampleNavItems, { body_comp: true })
    const healthGroup = groups.find((g) => g.rubric === 'health')

    expect(healthGroup).toBeDefined()
    const bodyCompItem = healthGroup?.items.find((it) => it.id === 'body_comp')
    expect(bodyCompItem).toBeDefined()
    expect(bodyCompItem?.titleKey).toBe('nav.body_comp')
    expect(bodyCompItem?.core).toBe(false)
    expect(bodyCompItem?.enabled).toBe(true)
  })

  it('marks core modules as core: true and respects enabledModules overrides for non-core', () => {
    const enabledModules = {
      workouts: false,
      skincare: false,
      body_comp: false,
    }
    const groups = groupSettingsModules(sampleNavItems, enabledModules)

    const healthGroup = groups.find((g) => g.rubric === 'health')!
    const weightItem = healthGroup.items.find((it) => it.id === 'weight')!
    const workoutsItem = healthGroup.items.find((it) => it.id === 'workouts')!
    const bodyCompItem = healthGroup.items.find((it) => it.id === 'body_comp')!

    // Weight is core: always core = true, enabled = true
    expect(weightItem.core).toBe(true)
    expect(weightItem.enabled).toBe(true)

    // Workouts is non-core: core = false, enabled = false
    expect(workoutsItem.core).toBe(false)
    expect(workoutsItem.enabled).toBe(false)

    // body_comp is non-core: core = false, enabled = false
    expect(bodyCompItem.core).toBe(false)
    expect(bodyCompItem.enabled).toBe(false)
  })

  it('handles empty nav items gracefully', () => {
    const groups = groupSettingsModules([], {})
    expect(groups).toEqual([])
  })
})
