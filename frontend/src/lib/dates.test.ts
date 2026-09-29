import { describe, expect, it } from 'vitest'
import { clockLabel, parseIsoDate, relativeDay } from './dates'

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
