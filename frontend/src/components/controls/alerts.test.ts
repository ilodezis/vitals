import { describe, expect, it } from 'vitest'
import { alertIdOf, toneOf, type SystemAlert } from './alerts'

const alert = (over: Partial<SystemAlert>): SystemAlert => ({
  id: 1,
  domain: 'weight',
  severity: 'warn',
  alertKey: 'k',
  message: 'Noisy period',
  overridden: false,
  ...over,
})

describe('toneOf', () => {
  it('keeps the four rungs and treats anything else as a heads-up', () => {
    expect(['note', 'info', 'warn', 'block'].map(toneOf)).toEqual(['note', 'info', 'warn', 'block'])
    expect(toneOf('critical')).toBe('info')
  })
})

describe('alertIdOf', () => {
  const alerts = [alert({ id: 7 }), alert({ id: 8, domain: 'labs', message: 'Vitamin D low' })]

  it('finds the alert a line of Today was made from', () => {
    expect(alertIdOf({ domain: 'labs', severity: 'warn', message: 'Vitamin D low' }, alerts)).toBe(8)
  })

  it('has nothing for a line that is not an alert', () => {
    expect(alertIdOf({ domain: 'garmin', severity: 'note', message: 'Slept well' }, alerts)).toBeUndefined()
    expect(alertIdOf({ domain: 'weight', severity: 'block', message: 'Noisy period' }, alerts)).toBeUndefined()
  })
})
