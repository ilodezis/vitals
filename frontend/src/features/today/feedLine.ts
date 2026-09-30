import type { Lang } from '@/lib/format'
import { formatCompact, formatInt, formatNumber } from '@/lib/format'
import type { TFn } from '@/lib/units'
import type { FeedRow } from './types'

/** The two lines of a feed row. An event carries the owner's own words; for the rest the server
 *  sends what the row is (`kind`) and its number, and the words are written here. */
export function feedLine(row: FeedRow, t: TFn, lang: Lang): { text: string; detail: string } {
  switch (row.kind) {
    case 'meal':
      return {
        text: row.text,
        detail: row.value ? t('today.src_meal', { value: formatInt(row.value, lang) }) : t('nav.nutrition'),
      }
    case 'signal': {
      const translated = t(`app.signal_key.${row.text}`)
      const keyLabel = translated !== `app.signal_key.${row.text}` ? translated : row.text.replaceAll('_', ' ')
      const valStr = row.value != null ? ` · ${formatCompact(row.value, lang)}` : ''
      return { text: `${keyLabel}${valStr}`, detail: t('today.src_bot') }
    }
    case 'brief':
      return { text: t('today.brief_sent'), detail: t('today.src_proactive') }
    case 'weight':
      return {
        text: t('app.feed.weight', { value: row.value === null ? '—' : formatNumber(row.value, lang) }),
        detail: t('app.source.manual'),
      }
    case 'event':
      return { text: row.text, detail: row.detail }
  }
}
