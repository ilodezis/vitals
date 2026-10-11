import { describe, expect, it } from 'vitest'
import { clockLabel, fieldDate, parseIsoDate, relativeDay } from './dates'

const labels = { today: 'Сегодня', yesterday: 'Вчера' }
const today = parseIsoDate('2026-09-29')

describe('relativeDay', () => {
  it('names today and yesterday', () => {
    expect(relativeDay(parseIsoDate('2026-09-29'), today, 'ru', labels)).toBe('Сегодня')
    expect(relativeDay(parseIsoDate('2026-09-28'), today, 'ru', labels)).toBe('Вчера')
  })

  it('names a day within the week by its weekday', () => {
    expect(relativeDay(parseIsoDate('2026-09-27'), today, 'ru', labels)).toBe('вс, 27 сен')
    expect(relativeDay(parseIsoDate('2026-09-27'), today, 'en', labels)).toBe('Sun, Sep 27')
  })

  it('gives an older day as a date', () => {
    expect(relativeDay(parseIsoDate('2026-09-01'), today, 'ru', labels)).toBe('1 сен')
  })
})

describe('clockLabel', () => {
  it('pads the hour and the minute', () => {
    expect(clockLabel(new Date(2026, 8, 29, 8, 5))).toBe('08:05')
    expect(clockLabel(new Date(2026, 8, 29, 23, 59))).toBe('23:59')
  })
})

describe('fieldDate', () => {
  it('names the weekday and the month in the reader\'s language', () => {
    expect(fieldDate(parseIsoDate('2026-10-11'), today, 'ru')).toBe('вс, 11 октября')
    expect(fieldDate(parseIsoDate('2026-10-11'), today, 'en')).toBe('Sun, October 11')
  })

  it('adds the year only when it is not this one', () => {
    expect(fieldDate(parseIsoDate('2025-12-28'), today, 'ru')).toBe('вс, 28 декабря 2025')
  })
})
