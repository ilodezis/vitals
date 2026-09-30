import { useMemo, type ReactNode } from 'react'
import type { Lang } from '@/lib/format'
import { I18nContext, type I18n } from './context'
import { plural, translate, translateOr, type Dictionary } from './translate'

/** Hands `useT()` the dictionary of one language. The language comes from the
 *  session (`GET /api/v1/session`); `loadDictionary` fetches the matching file. */
export function I18nProvider({
  lang,
  dictionary,
  children,
}: {
  lang: Lang
  dictionary: Dictionary
  children: ReactNode
}) {
  const value = useMemo<I18n>(
    () => ({
      lang,
      t: (key, params) => translate(dictionary, key, params),
      tOr: (key, fallback, params) => translateOr(dictionary, key, fallback, params),
      plural: (n, one, fewOrOther, many) => plural(lang, n, one, fewOrOther, many),
    }),
    [lang, dictionary],
  )
  return <I18nContext value={value}>{children}</I18nContext>
}
