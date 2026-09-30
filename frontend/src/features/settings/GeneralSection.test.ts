import { describe, expect, it } from 'vitest'
import { groupSettingsModules } from './GeneralSection'

const registry = [
  { key: 'weight', rubric: 'health', core: true },
  { key: 'hevy', rubric: 'health', core: false },
  { key: 'nutrition', rubric: 'health', core: false },
  { key: 'body_comp', rubric: 'health', core: false },
  { key: 'labs', rubric: 'markers', core: true },
  { key: 'genetics', rubric: 'markers', core: false },
  { key: 'skincare', rubric: 'lifestyle', core: false },
  { key: 'reports', rubric: 'journal', core: true },
]

describe('groupSettingsModules', () => {
  it('groups the registry by rubric, in the server order', () => {
    const groups = groupSettingsModules(registry, {})
    expect(groups.map((g) => g.rubric)).toEqual(['health', 'markers', 'lifestyle', 'journal'])
    expect(groups.map((g) => g.rubricKey)).toEqual([
      'masthead.rubric.health',
      'masthead.rubric.markers',
      'masthead.rubric.lifestyle',
      'masthead.rubric.journal',
    ])
  })

  it('keeps a switched-off module in the list, so it can be switched back on', () => {
    const groups = groupSettingsModules(registry, { genetics: false, nutrition: false })
    const ids = groups.flatMap((g) => g.items.map((it) => it.id))
    expect(ids).toContain('genetics')
    expect(ids).toContain('nutrition')
    const genetics = groups.flatMap((g) => g.items).find((it) => it.id === 'genetics')
    expect(genetics).toMatchObject({ core: false, enabled: false })
  })

  it('lists body composition with health and titles each module by its nav key', () => {
    const health = groupSettingsModules(registry, { body_comp: true }).find((g) => g.rubric === 'health')
    const bodyComp = health?.items.find((it) => it.id === 'body_comp')
    expect(bodyComp).toMatchObject({ titleKey: 'nav.body_comp', core: false, enabled: true })
  })

  it('shows core modules as always on and follows the switches for the rest', () => {
    const items = groupSettingsModules(registry, { hevy: true, skincare: false }).flatMap((g) => g.items)
    expect(items.find((it) => it.id === 'weight')).toMatchObject({ core: true, enabled: true })
    expect(items.find((it) => it.id === 'hevy')).toMatchObject({ core: false, enabled: true })
    expect(items.find((it) => it.id === 'skincare')).toMatchObject({ core: false, enabled: false })
  })

  it('handles an empty registry', () => {
    expect(groupSettingsModules([], {})).toEqual([])
  })
})
