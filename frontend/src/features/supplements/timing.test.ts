import { describe, expect, it } from 'vitest'
import { joinTiming, splitTiming, timingWorthShowing } from './timing'

describe('supplement timing', () => {
  it('reads one of the four words as a choice', () => {
    expect(splitTiming('night')).toEqual({ choice: 'night', custom: '' })
    expect(splitTiming('Morning')).toEqual({ choice: 'morning', custom: '' })
  })

  it('keeps any other text as its own', () => {
    expect(splitTiming('перед сном')).toEqual({ choice: 'custom', custom: 'перед сном' })
    expect(joinTiming('custom', '  with dinner ')).toBe('with dinner')
    expect(joinTiming('custom', '   ')).toBeNull()
    expect(joinTiming('night', 'ignored')).toBe('night')
  })

  it('starts a new entry in the morning', () => {
    expect(splitTiming(null)).toEqual({ choice: 'morning', custom: '' })
  })

  it('names the timing only where the group does not', () => {
    expect(timingWorthShowing('evening')).toBe(false)
    expect(timingWorthShowing('night')).toBe(true)
    expect(timingWorthShowing('with dinner')).toBe(true)
    expect(timingWorthShowing('')).toBe(false)
  })
})
