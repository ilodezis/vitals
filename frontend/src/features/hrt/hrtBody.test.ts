import { describe, expect, it } from 'vitest'
import { buildDoseBody, buildItemBody } from './hrtBody'

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
})
