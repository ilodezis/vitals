import { describe, expect, it } from 'vitest'
import { buildMeasureBody, buildWeightPatch } from './weightEdit'

describe('buildWeightPatch', () => {
  it('reads the weight however the decimal is typed', () => {
    expect(buildWeightPatch({ date: '2026-09-28', kg: '86,4', note: '' })).toEqual({ date: '2026-09-28', weight_kg: 86.4, note: null })
    expect(buildWeightPatch({ date: '2026-09-28', kg: ' 86.4 ', note: ' after a run ' })).toEqual({ date: '2026-09-28', weight_kg: 86.4, note: 'after a run' })
  })

  it('clears a note that was emptied instead of leaving the old one', () => {
    expect(buildWeightPatch({ date: '2026-09-28', kg: '86', note: '   ' })?.note).toBeNull()
  })

  it('is not a body without a date or a weight', () => {
    expect(buildWeightPatch({ date: '', kg: '86', note: '' })).toBeNull()
    expect(buildWeightPatch({ date: '2026-09-28', kg: '', note: '' })).toBeNull()
    expect(buildWeightPatch({ date: '2026-09-28', kg: 'heavy', note: '' })).toBeNull()
    expect(buildWeightPatch({ date: '2026-09-28', kg: '0', note: '' })).toBeNull()
  })
})

describe('buildMeasureBody', () => {
  it('sends every field of the row, an emptied one as null', () => {
    expect(buildMeasureBody({ date: '2026-09-28', neck: '38,5', waist: '', hips: '', note: '' })).toEqual({
      date: '2026-09-28',
      neck_cm: 38.5,
      waist_cm: null,
      hips_cm: null,
      note: null,
    })
  })

  it('keeps the note and the third circumference when they are there', () => {
    expect(buildMeasureBody({ date: '2026-09-28', neck: '34', waist: '70', hips: '96.5', note: ' tape ' })).toEqual({
      date: '2026-09-28',
      neck_cm: 34,
      waist_cm: 70,
      hips_cm: 96.5,
      note: 'tape',
    })
  })

  it('is not a body when a field holds something that is not a number', () => {
    expect(buildMeasureBody({ date: '2026-09-28', neck: 'abc', waist: '84', hips: '', note: '' })).toBeNull()
    expect(buildMeasureBody({ date: '', neck: '38', waist: '84', hips: '', note: '' })).toBeNull()
  })
})
