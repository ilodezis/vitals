import { describe, expect, it } from 'vitest'
import { buildInjectionPatch, buildPhaseBody, drugOptions } from './glp1Forms'

describe('buildInjectionPatch', () => {
  const base = { date: '2026-09-20', dose: '0,5', drug: 'semaglutide', site: 'thigh_left', note: ' evening ' }

  it('hands over the whole entry', () => {
    expect(buildInjectionPatch(base)).toEqual({ date: '2026-09-20', doseMg: 0.5, drug: 'semaglutide', site: 'thigh_left', note: 'evening' })
  })

  it('clears the site and the note that were taken off', () => {
    expect(buildInjectionPatch({ ...base, site: null, note: '' })).toMatchObject({ site: null, note: null })
  })

  it('is not a body without a date, a drug or a positive dose', () => {
    expect(buildInjectionPatch({ ...base, date: '' })).toBeNull()
    expect(buildInjectionPatch({ ...base, drug: '  ' })).toBeNull()
    expect(buildInjectionPatch({ ...base, dose: '' })).toBeNull()
    expect(buildInjectionPatch({ ...base, dose: '0' })).toBeNull()
    expect(buildInjectionPatch({ ...base, dose: '-1' })).toBeNull()
    expect(buildInjectionPatch({ ...base, dose: 'half' })).toBeNull()
  })
})

describe('buildPhaseBody', () => {
  const base = { start: '2026-09-01', end: '', drug: 'tirzepatide', dose: '2.5' }

  it('leaves an open phase without an end date', () => {
    expect(buildPhaseBody(base)).toEqual({ startDate: '2026-09-01', endDate: null, drug: 'tirzepatide', doseMg: 2.5 })
  })

  it('keeps the end date of a phase that is already over', () => {
    expect(buildPhaseBody({ ...base, end: '2026-09-28' })?.endDate).toBe('2026-09-28')
  })

  it('is not a body when the phase would end before it starts', () => {
    expect(buildPhaseBody({ ...base, end: '2026-08-01' })).toBeNull()
  })

  it('is not a body without a start, a drug or a positive dose', () => {
    expect(buildPhaseBody({ ...base, start: '' })).toBeNull()
    expect(buildPhaseBody({ ...base, drug: '' })).toBeNull()
    expect(buildPhaseBody({ ...base, dose: '0' })).toBeNull()
  })
})

describe('drugOptions', () => {
  it('offers the known drugs', () => {
    expect(drugOptions(null)).toEqual(['semaglutide', 'tirzepatide'])
  })

  it('keeps a drug the list does not know, so an edit cannot silently rename it', () => {
    expect(drugOptions('Retatrutide')).toEqual(['semaglutide', 'tirzepatide', 'Retatrutide'])
    expect(drugOptions('tirzepatide')).toEqual(['semaglutide', 'tirzepatide'])
  })
})
