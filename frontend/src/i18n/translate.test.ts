import { describe, expect, it } from 'vitest'
import { plural, translate } from './translate'

// The rules below are vitals/i18n.py's t() and plural(), restated: the same
// dictionary has to read the same on the server and in the app.

describe('translate', () => {
  const dict = {
    'nav.weight': 'Вес',
    'sync.days_ago': '{n} {word} назад',
    'today.said_weight': 'Вес {value} кг',
    'literal.braces': 'Скобки {{так}} пишутся',
    'alert.plateau': 'Плато на {drug} {dose:g} мг ({slope:+.2f} кг/нед)',
    'alert.fixed': '{value:.1f} кг',
  }

  it('returns the string as it is when there is nothing to fill in', () => {
    expect(translate(dict, 'nav.weight')).toBe('Вес')
  })

  it('returns the key itself for a string that does not exist', () => {
    expect(translate(dict, 'no.such.key')).toBe('no.such.key')
  })

  it('fills named placeholders, numbers included', () => {
    expect(translate(dict, 'sync.days_ago', { n: 3, word: 'дня' })).toBe('3 дня назад')
    expect(translate(dict, 'today.said_weight', { value: '86,1' })).toBe('Вес 86,1 кг')
  })

  it('leaves the string unfilled when a value is missing, as t() does', () => {
    expect(translate(dict, 'sync.days_ago', { n: 3 })).toBe('{n} {word} назад')
  })

  it('treats doubled braces as literal ones', () => {
    expect(translate(dict, 'literal.braces', { x: 1 })).toBe('Скобки {так} пишутся')
  })

  it('understands the two number specs the dictionaries use', () => {
    expect(translate(dict, 'alert.plateau', { drug: 'Ozempic', dose: 1.0, slope: -0.1234 })).toBe(
      'Плато на Ozempic 1 мг (-0.12 кг/нед)',
    )
    expect(translate(dict, 'alert.plateau', { drug: 'X', dose: 0.25, slope: 0.5 })).toBe(
      'Плато на X 0.25 мг (+0.50 кг/нед)',
    )
    expect(translate(dict, 'alert.fixed', { value: 7.456 })).toBe('7.5 кг')
  })

  it('formats {:g} like Python: six significant digits, no trailing zeros', () => {
    const g = { g: '{value:g}' }
    expect(translate(g, 'g', { value: 6 })).toBe('6')
    expect(translate(g, 'g', { value: 12.5 })).toBe('12.5')
    expect(translate(g, 'g', { value: 123456.7 })).toBe('123457')
    expect(translate(g, 'g', { value: 1234567 })).toBe('1.23457e+06')
    expect(translate(g, 'g', { value: 0.00001234 })).toBe('1.234e-05')
  })

  it('gives up on a number spec applied to text, leaving the string unfilled', () => {
    expect(translate(dict, 'alert.fixed', { value: 'n/a' })).toBe('{value:.1f} кг')
  })
})

describe('plural', () => {
  it('has two forms in English', () => {
    expect(plural('en', 1, 'session', 'sessions')).toBe('session')
    expect(plural('en', 0, 'session', 'sessions')).toBe('sessions')
    expect(plural('en', 2, 'session', 'sessions')).toBe('sessions')
    expect(plural('en', 21, 'session', 'sessions')).toBe('sessions')
  })

  it('has three forms in Russian', () => {
    const forms = ['сессия', 'сессии', 'сессий'] as const
    expect(plural('ru', 1, ...forms)).toBe('сессия')
    expect(plural('ru', 21, ...forms)).toBe('сессия')
    expect(plural('ru', 2, ...forms)).toBe('сессии')
    expect(plural('ru', 4, ...forms)).toBe('сессии')
    expect(plural('ru', 24, ...forms)).toBe('сессии')
    expect(plural('ru', 0, ...forms)).toBe('сессий')
    expect(plural('ru', 5, ...forms)).toBe('сессий')
    expect(plural('ru', 11, ...forms)).toBe('сессий')
    expect(plural('ru', 12, ...forms)).toBe('сессий')
    expect(plural('ru', 14, ...forms)).toBe('сессий')
    expect(plural('ru', 111, ...forms)).toBe('сессий')
  })

  it('falls back to the English rule in Russian when no third form is given', () => {
    expect(plural('ru', 1, 'день', 'дня')).toBe('день')
    expect(plural('ru', 2, 'день', 'дня')).toBe('дня')
  })

  it('counts a negative or fractional number by its whole part', () => {
    expect(plural('en', -1, 'day', 'days')).toBe('day')
    expect(plural('ru', 2.9, 'день', 'дня', 'дней')).toBe('дня')
  })

  it('answers with the last form for a number it cannot read', () => {
    expect(plural('ru', Number.NaN, 'день', 'дня', 'дней')).toBe('дней')
    expect(plural('en', Number.NaN, 'day', 'days')).toBe('days')
  })
})
