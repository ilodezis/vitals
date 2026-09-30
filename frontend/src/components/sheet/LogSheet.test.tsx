import { describe, expect, it } from 'vitest'
import {
  buildInjectionBody,
  buildMealBody,
  buildMeasureBody,
  parseLocaleNumber,
  selectDoseAlert,
} from './LogSheet'

const componentAndFeatureSources = import.meta.glob<string>(
  [
    '/src/components/**/*.{ts,tsx}',
    '/src/features/**/*.{ts,tsx}',
    '!/src/**/*.test.{ts,tsx}',
    '!/src/components/shell/stageMotion.ts',
  ],
  {
    query: '?raw',
    import: 'default',
    eager: true,
  },
)

describe('parseLocaleNumber', () => {
  it('parses numbers with comma or dot decimal separators', () => {
    expect(parseLocaleNumber('86,1')).toBe(86.1)
    expect(parseLocaleNumber(' 38.5 ')).toBe(38.5)
    expect(parseLocaleNumber('')).toBeUndefined()
    expect(parseLocaleNumber('abc')).toBeUndefined()
  })
})

describe('LogSheet request body builders', () => {
  it('builds meal payload with comma numbers', () => {
    expect(
      buildMealBody({
        date: '2026-09-30',
        time: '13:45',
        name: '  Гречка с курицей  ',
        kcalRaw: '520,5',
        proteinRaw: '42,3',
      }),
    ).toEqual({
      date: '2026-09-30',
      time: '13:45',
      name: 'Гречка с курицей',
      calories: 520.5,
      protein_g: 42.3,
      override: false,
    })
  })

  it('builds injection payload for current and custom doses', () => {
    expect(
      buildInjectionBody({
        date: '2026-09-30',
        mode: 'current',
        currentDoseMg: 0.5,
        drug: 'semaglutide',
        site: 'abdomen_left',
      }),
    ).toEqual({
      date: '2026-09-30',
      doseMg: 0.5,
      drug: 'semaglutide',
      site: 'abdomen_left',
      override: false,
    })

    expect(
      buildInjectionBody({
        date: '2026-09-30',
        mode: 'other',
        currentDoseMg: 0.5,
        customDoseRaw: '1,25',
        drug: 'semaglutide',
        site: 'thigh_right',
        override: true,
      }),
    ).toEqual({
      date: '2026-09-30',
      doseMg: 1.25,
      drug: 'semaglutide',
      site: 'thigh_right',
      override: true,
    })
  })

  it('builds measure payload with comma numbers', () => {
    expect(
      buildMeasureBody({
        date: '2026-09-30',
        waistRaw: '84,5',
        neckRaw: '39,2',
      }),
    ).toEqual({
      date: '2026-09-30',
      waist_cm: 84.5,
      neck_cm: 39.2,
      override: false,
    })
  })
})

describe('selectDoseAlert', () => {
  it('shows overdue alert without unscheduled evidence when overdue or daysToNext < 0', () => {
    const alert = selectDoseAlert({ daysToNext: -3, overdue: true })
    expect(alert).toEqual({
      tone: 'warn',
      textKey: 'app.log.dose.overdue',
      days: 3,
    })
    expect(alert?.evidenceKey).toBeUndefined()
  })

  it('shows early alert with unscheduled evidence when daysToNext > 0', () => {
    expect(selectDoseAlert({ daysToNext: 4, overdue: false })).toEqual({
      tone: 'warn',
      textKey: 'app.log.dose.early',
      days: 4,
      evidenceKey: 'app.log.dose.unscheduled',
    })
  })

  it('returns null when due today (daysToNext === 0)', () => {
    expect(selectDoseAlert({ daysToNext: 0, overdue: false })).toBeNull()
  })
})

describe('an injection is never logged with a dose nobody gave', () => {
  const base = { date: '2026-09-30', drug: 'semaglutide', site: 'abdomen_left' }

  it('builds no body while there is no current dose and none typed in', () => {
    expect(buildInjectionBody({ ...base, mode: 'current', currentDoseMg: null })).toBeNull()
    expect(buildInjectionBody({ ...base, mode: 'other', currentDoseMg: null })).toBeNull()
    expect(buildInjectionBody({ ...base, mode: 'other', currentDoseMg: null, customDoseRaw: '' })).toBeNull()
  })

  it('does not fall back to the current dose (or to a likely one) when the typed one is not a number', () => {
    expect(buildInjectionBody({ ...base, mode: 'other', currentDoseMg: 0.5, customDoseRaw: 'abc' })).toBeNull()
    expect(buildInjectionBody({ ...base, mode: 'other', currentDoseMg: 0.5, customDoseRaw: '0' })).toBeNull()
    expect(buildInjectionBody({ ...base, mode: 'other', currentDoseMg: 0.5, customDoseRaw: '-1' })).toBeNull()
  })

  it('takes the typed dose when there is no current phase at all', () => {
    expect(buildInjectionBody({ ...base, mode: 'other', currentDoseMg: null, customDoseRaw: '0,25', drug: null })).toEqual({
      date: '2026-09-30',
      doseMg: 0.25,
      drug: undefined,
      site: 'abdomen_left',
      override: false,
    })
  })

  it('has no alert to give while the cycle is not known', () => {
    expect(selectDoseAlert({ daysToNext: null })).toBeNull()
  })

  it('carries no made-up height, sex or dose in the sheet itself', () => {
    const source = Object.entries(componentAndFeatureSources).find(([file]) => file.endsWith('/sheet/LogSheet.tsx'))?.[1] ?? ''
    expect(source).not.toBe('')
    expect(source).not.toMatch(/\?\?\s*190\b|\?\?\s*'male'|fallbackDose|\?\s*[a-zA-Z.]+\s*:\s*0\.5\b/)
    // The API has no such field, so the sheet has no control for it.
    expect(source).not.toMatch(/breakfast|lunch|dinner|snack/)
  })
})

describe('no fake save timers in components/ and features/', () => {
  it('forbids setTimeout(resolve outside lib/motion.ts and shell/stageMotion.ts', () => {
    const entries = Object.entries(componentAndFeatureSources)
    expect(entries.length).toBeGreaterThan(20)
    const offenders = entries
      .filter(([, content]) => content.includes('setTimeout(resolve'))
      .map(([file]) => file)
    expect(offenders).toEqual([])
  })
})
