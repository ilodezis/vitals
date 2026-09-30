import { describe, expect, it } from 'vitest'
import type { components } from '@/api/schema'
import { toWeightView } from './useWeightView'

type RawWeightView = components['schemas']['WeightView']

/** A server that has nothing yet: one weigh-in at most, no goal, no dose, no scan. */
const bare = (over: Partial<RawWeightView> = {}): RawWeightView => ({
  drug: 'semaglutide',
  dose_phases: [],
  history: [],
  pace: { dose: null, goal: null, per_week_kg: null },
  trend: [],
  weighings: [],
  ...over,
})

describe('toWeightView', () => {
  it('keeps what the server does not have as null, never as a likely number', () => {
    const view = toWeightView(bare({ latest_kg: null, last_scan: null }))

    expect(view.kg).toBeNull()
    expect(view.average7).toBeNull()
    expect(view.weekDeltaKg).toBeNull()
    expect(view.bodyFatPct).toBeNull()
    expect(view.bodyFatSource).toBeNull()
    expect(view.lastScan).toBeNull()
    expect(view.pace).toEqual({ perWeekKg: null, dose: null, goal: null })
  })

  it('leaves the goal out until there is one', () => {
    expect(toWeightView(bare({ pace: { goal: null, dose: null, per_week_kg: -0.6 } })).pace.goal).toBeNull()
    const withGoal = toWeightView(bare({ pace: { goal: { target_kg: 80, weeks: 10 }, dose: null, per_week_kg: -0.6 } }))
    expect(withGoal.pace.goal).toEqual({ targetKg: 80, weeks: 10 })
  })

  it('reads a goal that cannot be reached at this pace as having no weeks', () => {
    const view = toWeightView(bare({ pace: { goal: { target_kg: 80, weeks: null }, dose: null, per_week_kg: 0.1 } }))
    expect(view.pace.goal).toEqual({ targetKg: 80, weeks: null })
  })

  it('keeps a dose whose change is not known yet, without a label of its own', () => {
    const view = toWeightView(bare({ pace: { goal: null, per_week_kg: null, dose: { drug: 'semaglutide', dose_mg: 0.25, since_date: '2026-08-02', days: 58, delta_kg: null } } }))

    expect(view.pace.dose).toEqual({ drug: 'semaglutide', doseMg: 0.25, sinceIso: '2026-08-02', days: 58, deltaKg: null })
    expect(view.pace.dose).not.toHaveProperty('label')
  })

  it('carries the scan the server names, and the source of the body-fat figure', () => {
    const view = toWeightView(
      bare({
        latest_kg: 86.3,
        body_fat_pct: 18.4,
        body_fat_source: 'InBody 770',
        last_scan: { device: 'InBody 770', date: '2026-09-12', rows: [{ label: 'Body fat', value: 18.4, unit: '%' }] },
      }),
    )

    expect(view.kg).toBe(86.3)
    expect(view.bodyFatSource).toBe('InBody 770')
    expect(view.lastScan).toEqual({ device: 'InBody 770', dateIso: '2026-09-12', rows: [{ label: 'Body fat', value: 18.4, unit: '%' }] })
  })
})
