/** Bodies of the two dose forms. A field that is empty or not a number is `null`, and the
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

export function buildItemBody(fields: {
  dose: string
  interval: string
  startWeek: string
}): { dose: number; intervalDays: number; startWeek: number } | null {
  const dose = positive(fields.dose)
  const intervalDays = positive(fields.interval)
  const startWeek = wholeFrom1(fields.startWeek)
  return dose === null || intervalDays === null || startWeek === null ? null : { dose, intervalDays, startWeek }
}
