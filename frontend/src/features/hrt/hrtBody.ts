/** Bodies of the dose and plan forms. A field that is empty or not a number is `null`, and the
 *  form stays unsaved: no dose is ever recorded that the person did not type. */

function positive(raw: string): number | null {
  const value = Number.parseFloat(raw)
  return Number.isFinite(value) && value > 0 ? value : null
}

function wholeFrom1(raw: string): number | null {
  const text = raw.trim()
  if (!/^\d+$/.test(text)) return null
  const value = Number(text)
  return value >= 1 ? value : null
}

export function buildDoseBody(fields: { dose: string }): { dose: number } | null {
  const dose = positive(fields.dose)
  return dose === null ? null : { dose }
}

export interface ItemBody {
  dose: number
  intervalDays: number
  startWeek: number
  /** How long the segment runs; left out, it runs to the end of the cycle. */
  durationDays?: number
}

export function buildItemBody(fields: { dose: string; interval: string; startWeek: string; duration?: string }): ItemBody | null {
  const dose = positive(fields.dose)
  const intervalDays = positive(fields.interval)
  const startWeek = wholeFrom1(fields.startWeek)
  if (dose === null || intervalDays === null || startWeek === null) return null
  const typedDuration = (fields.duration ?? '').trim()
  if (typedDuration === '') return { dose, intervalDays, startWeek }
  const durationDays = wholeFrom1(typedDuration)
  return durationDays === null ? null : { dose, intervalDays, startWeek, durationDays }
}

/** A change to a planned compound. A flat schedule (one fixed dose) is rewritten whole; a ramp
 *  or a schedule of several segments keeps its doses and only moves its start week. */
export function buildItemPatch(fields: { flat: boolean; dose: string; interval: string; startWeek: string; duration: string }): ItemBody | { startWeek: number } | null {
  if (fields.flat) return buildItemBody(fields)
  const startWeek = wholeFrom1(fields.startWeek)
  return startWeek === null ? null : { startWeek }
}

/** The file a template is saved as when it cannot be copied. */
export function templateFileName(name: string): string {
  const safe = [...name].map((ch) => (/[\p{L}\p{N}_-]/u.test(ch) ? ch : '_')).join('').slice(0, 64)
  return `hrt_template_${safe === '' ? 'template' : safe}.json`
}
