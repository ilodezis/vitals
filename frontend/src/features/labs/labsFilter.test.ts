import { describe, expect, it } from 'vitest'
import { deriveLabGroups, filterLabMarkers, normalizeGroupKey } from './LabsScreen'
import type { LabMarker } from './types'

describe('normalizeGroupKey', () => {
  it('normalizes Russian and English aliases', () => {
    expect(normalizeGroupKey('metabolism')).toBe('metabolic')
    expect(normalizeGroupKey('метаболизм')).toBe('metabolic')
    expect(normalizeGroupKey('hormones')).toBe('hormones')
    expect(normalizeGroupKey('гормоны')).toBe('hormones')
    expect(normalizeGroupKey('hrt_panel')).toBe('hrt_panel')
    expect(normalizeGroupKey('hrt')).toBe('hrt_panel')
    expect(normalizeGroupKey('Панель ГЗТ')).toBe('hrt_panel')
    expect(normalizeGroupKey('ГЗТ')).toBe('hrt_panel')
  })
})

describe('labs group filter (B4)', () => {
  const dummyHistory = [{ dateIso: '2026-09-01', value: 20 }]
  const sampleMarkers: LabMarker[] = [
    {
      id: 'glucose',
      name: 'Глюкоза',
      groupKey: 'metabolic',
      group: 'Метаболизм',
      unit: 'ммоль/л',
      value: 5.1,
      lo: 3.9,
      hi: 6.1,
      min: 2.0,
      max: 10.0,
      decimals: 1,
      history: dummyHistory,
    },
    {
      id: 'testo',
      name: 'Тестостерон общий',
      groupKey: 'hrt_panel',
      group: 'Панель ГЗТ',
      unit: 'нмоль/л',
      value: 28.5,
      lo: 12.0,
      hi: 33.0,
      min: 5.0,
      max: 50.0,
      decimals: 1,
      history: dummyHistory,
    },
    {
      id: 'tsh',
      name: 'ТТГ',
      groupKey: 'thyroid',
      group: 'Щитовидная железа',
      unit: 'мЕд/л',
      value: 2.1,
      lo: 0.4,
      hi: 4.0,
      min: 0.1,
      max: 8.0,
      decimals: 2,
      history: dummyHistory,
    },
  ]

  it('hides hrt_panel tab when HRT is disabled, but keeps markers in "all"', () => {
    const translate = (key: string, fallback: string) => (key === 'app.lab_cat.hrt_panel' ? 'Панель ГЗТ' : fallback)
    const groups = deriveLabGroups(sampleMarkers, false, translate)
    const groupKeys = groups.map(([key]) => key)

    // hrt_panel tab must be hidden
    expect(groupKeys).not.toContain('hrt_panel')
    expect(groupKeys).toContain('metabolic')
    expect(groupKeys).toContain('thyroid')

    // But in "all" filter, the HRT marker must still be present
    const all = filterLabMarkers(sampleMarkers, 'all', false)
    expect(all.map((m) => m.id)).toEqual(['glucose', 'testo', 'tsh'])
  })

  it('shows hrt_panel tab with translation when HRT is enabled', () => {
    const translate = (key: string, fallback: string) => (key === 'app.lab_cat.hrt_panel' ? 'Панель ГЗТ' : fallback)
    const groups = deriveLabGroups(sampleMarkers, true, translate)
    const groupKeys = groups.map(([key]) => key)

    expect(groupKeys).toContain('hrt_panel')
    const hrtGroup = groups.find(([key]) => key === 'hrt_panel')
    expect(hrtGroup?.[1]).toBe('Панель ГЗТ')

    // Filtering by hrt_panel returns only HRT markers
    const hrtOnly = filterLabMarkers(sampleMarkers, 'hrt_panel', true)
    expect(hrtOnly.map((m) => m.id)).toEqual(['testo'])
  })
})
