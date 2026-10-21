import { describe, expect, it } from 'vitest'
import { nudgesOf } from './NotificationsSection'

describe('nudgesOf', () => {
  it('reads the defaults when nothing is saved: everything but activity is on', () => {
    expect(nudgesOf(undefined)).toEqual({ activity: false, nutrition: true, data: true, environment: true, skincare: true })
  })

  it('reads the full names and the old one-letter keys alike', () => {
    expect(nudgesOf({ activity: true, nutrition: false })).toMatchObject({ activity: true, nutrition: false })
    expect(nudgesOf({ a: true, d: false, e: false })).toMatchObject({ activity: true, data: false, environment: false })
  })

  it('keeps the skincare checklist switched off once it was', () => {
    expect(nudgesOf({ skincare: false }).skincare).toBe(false)
  })
})
