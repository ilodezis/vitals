import type { I18n } from '@/i18n/context'

/** "1 приём", "3 приёма", "5 приёмов": the number and the form that agrees with it. */
export function mealsLabel(n: number, t: I18n['t'], plural: I18n['plural']): string {
  return plural(n, t('app.nutrition.meals_n.one', { n }), t('app.nutrition.meals_n.few', { n }), t('app.nutrition.meals_n.many', { n }))
}
