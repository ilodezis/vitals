import { use } from 'react'
import { I18nContext, type I18n } from './context'

/** `const { t, plural, lang } = useT()` — the current language's strings. */
export function useT(): I18n {
  const i18n = use(I18nContext)
  if (i18n === null) throw new Error('useT() needs an <I18nProvider> above it')
  return i18n
}
