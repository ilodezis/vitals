import { useT } from '@/i18n/useT'
import { parseIsoDate, relativeDay } from '@/lib/dates'
import { formatNumber } from '@/lib/format'
import { useLatestWeight } from './weightLog'

/** "last 86,1 · yesterday" — the reading the stepper starts from and how old it is; `null` before
 *  there has ever been one. */
export function useLastWeighed(): string | null {
  const { t, lang } = useT()
  const { kg, date, today } = useLatestWeight()
  if (kg === null || date === null || today === null) return null
  const when = relativeDay(parseIsoDate(date), parseIsoDate(today), lang, {
    today: t('app.today_word').toLowerCase(),
    yesterday: t('app.yesterday_word').toLowerCase(),
  })
  return t('app.today.weight_last', { value: formatNumber(kg, lang), when })
}
