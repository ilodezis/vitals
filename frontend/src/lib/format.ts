/* The one place numbers become text. The API sends raw numbers; every figure on
   screen goes through here so the two languages read the same way everywhere. */

export type Lang = 'ru' | 'en'

const MINUS = '−'
const GROUP = ' ' // narrow no-break space: "12 345" never wraps
const DECIMAL: Record<Lang, string> = { ru: ',', en: '.' }

const formatters = new Map<string, Intl.NumberFormat>()

function formatter(lang: Lang, digits: number): Intl.NumberFormat {
  const key = `${lang}:${digits}`
  let nf = formatters.get(key)
  if (nf === undefined) {
    nf = new Intl.NumberFormat(lang, {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
      // Group from four digits in both languages ("2 150", not "2150").
      useGrouping: 'always',
      // A value that rounds to zero keeps no sign: "−0,0" reads as a real change.
      signDisplay: 'negative',
    })
    formatters.set(key, nf)
  }
  return nf
}

/** A whole number, grouped: 2150 → "2 150". */
export const formatInt = (value: number, lang: Lang): string => formatNumber(value, lang, 0)

/** A number that reads as it was written: "94", not "94,0"; "93,9" when there is a tenth to keep. */
export function formatCompact(value: number, lang: Lang): string {
  return formatNumber(value, lang, Number.isInteger(Number(value.toFixed(1))) ? 0 : 1)
}

/** A change: the sign is always shown ("+0,4", "−0,6"); a value that rounds to zero has none. */
export function formatSigned(value: number, lang: Lang, digits = 1): string {
  const rounded = Number(value.toFixed(digits))
  const body = formatNumber(Math.abs(rounded), lang, digits)
  return rounded > 0 ? `+${body}` : rounded < 0 ? `${MINUS}${body}` : body
}

/** 86.14 → "86,1" (ru) / "86.1" (en); −0.42 → "−0,4"; 12345.67 → "12 345,7". */
export function formatNumber(value: number, lang: Lang, digits = 1): string {
  let out = ''
  for (const part of formatter(lang, digits).formatToParts(value)) {
    switch (part.type) {
      case 'minusSign':
        out += MINUS
        break
      case 'group':
        out += GROUP
        break
      case 'decimal':
        out += DECIMAL[lang]
        break
      default:
        out += part.value
    }
  }
  return out
}
