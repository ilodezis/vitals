import { createContext } from 'react'
import type { Lang } from '@/lib/format'
import type { Params } from './translate'

export interface I18n {
  lang: Lang
  /** The string for `key` in the current language, placeholders filled from `params`. */
  t: (key: string, params?: Params) => string
  /** The form of a word that goes with `n` in the current language. */
  plural: (n: number, one: string, fewOrOther: string, many?: string) => string
}

export const I18nContext = createContext<I18n | null>(null)
