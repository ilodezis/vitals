import { describe, expect, it } from 'vitest'
import { formatNumber } from './format'

const MINUS = '−'
const THIN = ' ' // narrow no-break space

describe('formatNumber', () => {
  it('uses a decimal comma in Russian and a point in English', () => {
    expect(formatNumber(86.14, 'ru')).toBe('86,1')
    expect(formatNumber(86.14, 'en')).toBe('86.1')
  })

  it('writes negatives with a real minus sign, not a hyphen', () => {
    expect(formatNumber(-0.42, 'ru')).toBe(`${MINUS}0,4`)
    expect(formatNumber(-0.42, 'en')).toBe(`${MINUS}0.4`)
  })

  it('groups thousands with a narrow no-break space in both languages', () => {
    expect(formatNumber(12345.67, 'ru')).toBe(`12${THIN}345,7`)
    expect(formatNumber(12345.67, 'en')).toBe(`12${THIN}345.7`)
    expect(formatNumber(2150, 'ru', 0)).toBe(`2${THIN}150`)
  })

  it('keeps the requested number of decimals', () => {
    expect(formatNumber(86, 'ru')).toBe('86,0')
    expect(formatNumber(7.456, 'en', 2)).toBe('7.46')
    expect(formatNumber(1234.5, 'en', 0)).toBe(`1${THIN}235`)
  })

  it('never prints a signed zero', () => {
    expect(formatNumber(-0.04, 'ru')).toBe('0,0')
  })
})
