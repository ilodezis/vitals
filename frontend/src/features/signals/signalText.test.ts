import { describe, expect, it } from 'vitest'
import { signalTime, signalValue } from './signalText'

describe('signal text', () => {
  it('keeps a whole value whole and a fractional value as written', () => {
    expect(signalValue(3, null, 'ru')).toBe('3')
    expect(signalValue(0.25, null, 'ru')).toBe('0,25')
    expect(signalValue(7.5, 'h', 'en')).toBe('7.5 h')
  })

  it('cuts the seconds off a time of day', () => {
    expect(signalTime('09:00:00')).toBe('09:00')
    expect(signalTime('9:05')).toBe('9:05')
  })
})
