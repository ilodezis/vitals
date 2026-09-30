import { describe, expect, it } from 'vitest'
import { clockTime, formatCompact, formatCompactNumber, formatNumber, formatPercent } from './format'

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

describe('formatCompact', () => {
  it('drops the decimal from a whole number and keeps one otherwise', () => {
    expect(formatCompact(94, 'ru')).toBe('94')
    expect(formatCompact(85.0, 'en')).toBe('85')
    expect(formatCompact(93.9, 'ru')).toBe('93,9')
    expect(formatCompact(8.94, 'en')).toBe('8.9')
  })

  it('does not print a whole number that only rounds to one as a decimal', () => {
    expect(formatCompact(9.04, 'ru')).toBe('9')
  })
})

describe('formatCompact with finer digits', () => {
  it('keeps a dose and a ratio as they were written', () => {
    expect(formatCompact(0.25, 'ru', 2)).toBe('0,25')
    expect(formatCompact(0.5, 'ru', 2)).toBe('0,5')
    expect(formatCompact(3.5, 'ru', 2)).toBe('3,5')
    expect(formatCompact(0.381, 'ru', 3)).toBe('0,381')
    expect(formatCompact(0.381, 'en', 3)).toBe('0.381')
  })

  it('never pads a whole number', () => {
    expect(formatCompact(79, 'ru', 3)).toBe('79')
    expect(formatCompact(86.0, 'ru', 2)).toBe('86')
    expect(formatCompact(19.6, 'ru', 3)).toBe('19,6')
  })
})

describe('formatPercent', () => {
  it('sets the sign apart in Russian and against the number in English', () => {
    expect(formatPercent(92, 'ru')).toBe('92\u00a0%')
    expect(formatPercent(92, 'en')).toBe('92%')
    expect(formatPercent(19.6, 'ru', 1)).toBe('19,6\u00a0%')
  })
})

describe('clockTime', () => {
  it('drops the seconds', () => {
    expect(clockTime('09:00:00')).toBe('09:00')
    expect(clockTime('9:05')).toBe('9:05')
    expect(clockTime('')).toBe('')
  })
})

describe('formatCompactNumber', () => {
  it('formats numbers compactly without English k in Russian', () => {
    expect(formatCompactNumber(9500, 'ru')).toContain('9,5')
    expect(formatCompactNumber(9500, 'ru')).not.toContain('k')
    expect(formatCompactNumber(9500, 'en')).toBe('9.5K')
  })
})

