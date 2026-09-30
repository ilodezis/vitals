import { describe, expect, it } from 'vitest'
import { plural, translate, type Dictionary } from '@/i18n/translate'
import { mealsLabel } from './mealsLabel'

const RU: Dictionary = {
  'app.nutrition.meals_n.one': '{n} приём',
  'app.nutrition.meals_n.few': '{n} приёма',
  'app.nutrition.meals_n.many': '{n} приёмов',
}
const EN: Dictionary = {
  'app.nutrition.meals_n.one': '{n} meal',
  'app.nutrition.meals_n.few': '{n} meals',
  'app.nutrition.meals_n.many': '{n} meals',
}

const label = (lang: 'ru' | 'en', dict: Dictionary, n: number) =>
  mealsLabel(n, (key, params) => translate(dict, key, params), (count, one, few, many) => plural(lang, count, one, few, many))

describe('mealsLabel', () => {
  it('agrees with the count in Russian', () => {
    expect([0, 1, 2, 3, 4, 5, 11, 21, 22, 25].map((n) => label('ru', RU, n))).toEqual([
      '0 приёмов', '1 приём', '2 приёма', '3 приёма', '4 приёма', '5 приёмов', '11 приёмов', '21 приём', '22 приёма', '25 приёмов',
    ])
  })

  it('has two forms in English', () => {
    expect([0, 1, 2, 30].map((n) => label('en', EN, n))).toEqual(['0 meals', '1 meal', '2 meals', '30 meals'])
  })
})
