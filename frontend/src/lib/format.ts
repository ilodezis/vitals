/* The one place numbers become text. The API sends raw numbers; every figure on
   screen goes through here so the two languages read the same way everywhere. */

export type Lang = 'ru' | 'en'

const MINUS = '−'
const GROUP = ' ' // narrow no-break space: "12 345" never wraps
const NBSP = '\u00a0'
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

/** A number that reads as it was written: "94", not "94,0"; "93,9" when there is a tenth to keep.
 *  `maxDigits` is how fine it may get: a dose (0,25) or a ratio (0,381) keeps its own digits. */
export function formatCompact(value: number, lang: Lang, maxDigits = 1): string {
  const rounded = Number(value.toFixed(maxDigits))
  let digits = 0
  while (digits < maxDigits && Number(rounded.toFixed(digits)) !== rounded) digits += 1
  return formatNumber(rounded, lang, digits)
}

/** A share: "92 %" in Russian (the sign stands apart, on a no-break space), "92%" in English. */
export function formatPercent(value: number, lang: Lang, maxDigits = 0): string {
  return `${formatCompact(value, lang, maxDigits)}${lang === 'ru' ? NBSP : ''}%`
}

/** "09:00:00" → "09:00": a time of day is read to the minute. */
export const clockTime = (time: string): string => (/^\d{1,2}:\d{2}/.test(time) ? time.slice(0, time.indexOf(':') + 3) : time)

/** Compact number notation (e.g. 9500 → "9,5 тыс." in ru, "9.5K" in en). */
export function formatCompactNumber(value: number, lang: Lang): string {
  const nf = new Intl.NumberFormat(lang, { notation: 'compact', maximumFractionDigits: 1 })
  let out = ''
  for (const part of nf.formatToParts(value)) {
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

/** ["SpO₂ 93 %", null, "Body Battery +55"] → "SpO₂ 93 % · Body Battery +55": only what is known,
 *  so a missing reading leaves no separator behind. */
export function joinKnown(parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(' · ')
}
