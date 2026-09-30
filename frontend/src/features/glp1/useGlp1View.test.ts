import { describe, expect, it } from 'vitest'
import type { components } from '@/api/schema'
import { toGlp1View } from './useGlp1View'

type RawGlp1View = components['schemas']['Glp1View']

/** What the server sends before a single injection has been logged. */
const EMPTY: RawGlp1View = {
  cycle: { overdue: false, unscheduled: false },
  dosePhases: [],
  injections: [],
  sideEffects: [],
  siteLabels: {},
  trend: [],
}

describe('toGlp1View', () => {
  it('has no dose, drug, cycle or change to show until there is an injection', () => {
    const view = toGlp1View(EMPTY)

    expect(view.drug).toBeNull()
    expect(view.doseMg).toBeNull()
    expect(view.sinceIso).toBeNull()
    expect(view.dayOnDose).toBeNull()
    expect(view.deltaOnDoseKg).toBeNull()
    expect(view.cycle).toEqual({ lastIso: null, nextIso: null, daysToNext: null, overdue: false, unscheduled: false })
    expect(view).not.toHaveProperty('summary')
  })

  it('keeps a negative count of days for an overdue injection', () => {
    const view = toGlp1View({ ...EMPTY, cycle: { lastIso: '2026-09-20', nextIso: '2026-09-27', daysToNext: -3, overdue: true, unscheduled: false } })

    expect(view.cycle.daysToNext).toBe(-3)
    expect(view.cycle.overdue).toBe(true)
  })

  it('keeps an injection that was logged without a site', () => {
    const view = toGlp1View({ ...EMPTY, injections: [{ dateIso: '2026-09-20', doseMg: 0.5, site: null }] })

    expect(view.injections).toEqual([{ dateIso: '2026-09-20', site: null, doseMg: 0.5 }])
  })
})
