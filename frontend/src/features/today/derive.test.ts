import { describe, expect, it } from 'vitest'
import { corridorStatus, forecastPhrase, goalProgress, splitNarrative } from './derive'

describe('splitNarrative', () => {
  it('sets the first sentence apart from the rest', () => {
    expect(splitNarrative('Вес 86,1 и уходит на 0,6 в неделю. Сон 82, но HRV ниже нормы.')).toEqual({
      lead: 'Вес 86,1 и уходит на 0,6 в неделю.',
      note: 'Сон 82, но HRV ниже нормы.',
    })
  })

  it('keeps a one-sentence line whole', () => {
    expect(splitNarrative('Вес 86.1 кг, тренд −0.6 кг/нед, сон 82, HRV 46.')).toEqual({
      lead: 'Вес 86.1 кг, тренд −0.6 кг/нед, сон 82, HRV 46.',
      note: '',
    })
  })

  it('does not break a sentence at a decimal point', () => {
    expect(splitNarrative('Weight is 86.1 and trending down. Sleep was 82.')).toEqual({
      lead: 'Weight is 86.1 and trending down.',
      note: 'Sleep was 82.',
    })
  })

  it('carries everything after the first sentence, across paragraphs', () => {
    expect(splitNarrative('Первое.\n\nВторое! Третье?')).toEqual({ lead: 'Первое.', note: 'Второе! Третье?' })
  })

  it('has nothing to say about nothing', () => {
    expect(splitNarrative('')).toEqual({ lead: '', note: '' })
    expect(splitNarrative('   ')).toEqual({ lead: '', note: '' })
  })
})

describe('goalProgress', () => {
  it('is the distance covered from where he started', () => {
    expect(goalProgress({ start_kg: 100, current_kg: 94, target_kg: 85 })).toEqual({ done: 6, total: 15, pct: 40 })
  })

  it('never leaves the bar', () => {
    expect(goalProgress({ start_kg: 100, current_kg: 101, target_kg: 85 }).pct).toBe(0)
    expect(goalProgress({ start_kg: 100, current_kg: 80, target_kg: 85 }).pct).toBe(100)
  })

  it('has no progress toward a goal that is not below the start', () => {
    expect(goalProgress({ start_kg: 80, current_kg: 80, target_kg: 85 })).toEqual({ done: 0, total: -5, pct: 0 })
  })
})

describe('corridorStatus', () => {
  const corridor = { lo: 50, hi: 58 }

  it('says where a value sits against its range', () => {
    expect(corridorStatus(46, corridor)).toBe('below')
    expect(corridorStatus(54, corridor)).toBe('in')
    expect(corridorStatus(50, corridor)).toBe('in')
    expect(corridorStatus(58, corridor)).toBe('in')
    expect(corridorStatus(61, corridor)).toBe('above')
  })

  it('says nothing without a value or a range', () => {
    expect(corridorStatus(null, corridor)).toBeNull()
    expect(corridorStatus(54, null)).toBeNull()
  })
})

describe('forecastPhrase', () => {
  const date = '2026-12-10'

  it('names how far ahead of the deadline it lands', () => {
    expect(forecastPhrase({ date, days_ahead: 17 })).toEqual({ key: 'app.today.forecast_early', days: 17 })
  })

  it('names how far behind it lands', () => {
    expect(forecastPhrase({ date, days_ahead: -4 })).toEqual({ key: 'app.today.forecast_late', days: 4 })
  })

  it('says so when it lands on the day', () => {
    expect(forecastPhrase({ date, days_ahead: 0 })).toEqual({ key: 'app.today.forecast_on_time', days: 0 })
  })

  it('gives just the date when there is no deadline to measure against', () => {
    expect(forecastPhrase({ date, days_ahead: null })).toEqual({ key: 'app.today.forecast', days: 0 })
  })
})
