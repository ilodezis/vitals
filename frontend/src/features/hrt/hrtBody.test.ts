import { describe, expect, it } from 'vitest'
import { buildDoseBody, buildItemBody, buildItemPatch, templateFileName } from './hrtBody'

describe('buildDoseBody', () => {
  it('reads the typed dose', () => {
    expect(buildDoseBody({ dose: '62.5' })).toEqual({ dose: 62.5 })
  })

  it('has no body for an empty, zero, negative or unreadable dose', () => {
    for (const dose of ['', '  ', '0', '-5', 'abc']) expect(buildDoseBody({ dose })).toBeNull()
  })
})

describe('buildItemBody', () => {
  it('reads all three fields as typed', () => {
    expect(buildItemBody({ dose: '125', interval: '3.5', startWeek: '2' })).toEqual({
      dose: 125,
      intervalDays: 3.5,
      startWeek: 2,
    })
  })

  it('does not fill an empty interval or week with a stand-in', () => {
    expect(buildItemBody({ dose: '125', interval: '', startWeek: '1' })).toBeNull()
    expect(buildItemBody({ dose: '125', interval: '3.5', startWeek: '' })).toBeNull()
  })

  it('needs a positive dose', () => {
    expect(buildItemBody({ dose: '', interval: '3.5', startWeek: '1' })).toBeNull()
    expect(buildItemBody({ dose: '0', interval: '3.5', startWeek: '1' })).toBeNull()
  })

  it('needs a week of 1 or more', () => {
    expect(buildItemBody({ dose: '125', interval: '3.5', startWeek: '0' })).toBeNull()
  })

  it('carries a duration only when one was typed, and only a whole number of days', () => {
    expect(buildItemBody({ dose: '125', interval: '3.5', startWeek: '1', duration: '28' })).toEqual({
      dose: 125,
      intervalDays: 3.5,
      startWeek: 1,
      durationDays: 28,
    })
    expect(buildItemBody({ dose: '125', interval: '3.5', startWeek: '1', duration: '' })).not.toHaveProperty('durationDays')
    expect(buildItemBody({ dose: '125', interval: '3.5', startWeek: '1', duration: '2.5' })).toBeNull()
    expect(buildItemBody({ dose: '125', interval: '3.5', startWeek: '1', duration: '0' })).toBeNull()
  })
})

describe('buildItemPatch', () => {
  const fields = { dose: '150', interval: '7', startWeek: '3', duration: '' }

  it('rewrites the dose and the interval of a flat schedule', () => {
    expect(buildItemPatch({ ...fields, flat: true })).toEqual({ dose: 150, intervalDays: 7, startWeek: 3 })
  })

  it('moves only the start week of a ramp, whatever the other fields hold', () => {
    expect(buildItemPatch({ ...fields, flat: false })).toEqual({ startWeek: 3 })
    expect(buildItemPatch({ dose: '', interval: '', duration: '', startWeek: '2', flat: false })).toEqual({ startWeek: 2 })
  })

  it('is not a body without a week, or without the dose of a flat schedule', () => {
    expect(buildItemPatch({ ...fields, startWeek: '', flat: false })).toBeNull()
    expect(buildItemPatch({ ...fields, dose: '', flat: true })).toBeNull()
  })
})

describe('templateFileName', () => {
  it('keeps letters, digits, dashes and underscores', () => {
    expect(templateFileName('TRT_cruise-2026')).toBe('hrt_template_TRT_cruise-2026.json')
  })

  it('replaces everything a file name may not hold', () => {
    expect(templateFileName('My TRT / blast: v2')).toBe('hrt_template_My_TRT___blast__v2.json')
  })

  it('has a name for a template without one', () => {
    expect(templateFileName('')).toBe('hrt_template_template.json')
  })
})
