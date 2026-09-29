/* The client's t() and plural() — vitals/i18n.py restated, so one dictionary reads
   the same on the server and in the app. Numbers are formatted by lib/format.ts
   before they get here; the specs below exist for the few strings whose
   placeholders carry one ({value:g}, {slope:+.2f}). */

import type { Lang } from '@/lib/format'

export type Dictionary = Readonly<Record<string, string>>
export type Params = Readonly<Record<string, string | number>>

// `{name}`, `{name:spec}`, and the doubled braces str.format() reads as literal ones.
const PLACEHOLDER = /\{\{|\}\}|\{([A-Za-z_]\w*)(?::([^{}]*))?\}/g
const NUMBER_SPEC = /^([+-]?)(?:\.(\d+))?([fg])$/

/** A value is missing or unfit for its spec: t() then returns the text unfilled. */
class Unfilled extends Error {}

/** `{value:g}` — six significant digits, no trailing zeros, like Python's. */
function general(n: number, precision: number): string {
  if (n === 0) return '0'
  const digits = Math.max(precision, 1)
  const [mantissa = '', exponent = '0'] = n.toExponential(digits - 1).split('e')
  const exp = Number(exponent)
  const strip = (s: string) => (s.includes('.') ? s.replace(/\.?0+$/, '') : s)
  if (exp < -4 || exp >= digits) {
    const abs = Math.abs(exp)
    return `${strip(mantissa)}e${exp < 0 ? '-' : '+'}${abs < 10 ? '0' : ''}${abs}`
  }
  return strip(n.toFixed(digits - 1 - exp))
}

function applySpec(value: string | number, spec: string): string {
  const match = NUMBER_SPEC.exec(spec)
  if (match === null) return String(value)
  const [, sign, decimals, kind] = match
  const n = typeof value === 'number' ? value : Number.NaN
  if (Number.isNaN(n)) throw new Unfilled()
  const text = kind === 'f' ? n.toFixed(decimals === undefined ? 6 : Number(decimals)) : general(n, decimals === undefined ? 6 : Number(decimals))
  return sign === '+' && n >= 0 ? `+${text}` : text
}

/** Look `key` up and fill its placeholders. A key that is not there comes back as
 *  itself; a value that is missing leaves the string unfilled — never a throw, so
 *  a bad string cannot take a screen down. */
export function translate(dict: Dictionary, key: string, params?: Params): string {
  const text = Object.hasOwn(dict, key) ? (dict[key] ?? key) : key
  if (params === undefined || Object.keys(params).length === 0) return text
  try {
    return text.replace(PLACEHOLDER, (token, name?: string, spec?: string) => {
      if (name === undefined) return token === '{{' ? '{' : '}'
      if (!Object.hasOwn(params, name)) throw new Unfilled()
      const value = params[name] as string | number
      return spec ? applySpec(value, spec) : String(value)
    })
  } catch (error) {
    if (error instanceof Unfilled) return text
    throw error
  }
}

/** English has two forms (one / other), Russian three (1, 21… / 2–4 / the rest).
 *  Without a third form even Russian falls back to the English rule. The count is
 *  taken by its whole part, sign ignored. */
export function plural(lang: Lang, n: number, one: string, fewOrOther: string, many?: string): string {
  const count = Math.abs(Math.trunc(n))
  if (!Number.isFinite(count)) return many ?? fewOrOther
  if (lang === 'ru' && many !== undefined) {
    if (count % 10 === 1 && count % 100 !== 11) return one
    if (count % 10 >= 2 && count % 10 <= 4 && !(count % 100 >= 12 && count % 100 <= 14)) {
      return fewOrOther
    }
    return many
  }
  return count === 1 ? one : fewOrOther
}
