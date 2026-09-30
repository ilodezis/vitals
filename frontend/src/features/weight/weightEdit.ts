/** Bodies of the two edit forms. A form that does not hold a whole, readable entry is `null`
 *  and stays unsaved: nothing the person did not type is ever written. */

/** A typed number, with a comma or a point; `null` for an empty field, `NaN` for anything else. */
function typed(raw: string): number | null {
  const text = raw.trim().replace(',', '.')
  if (text === '') return null
  return /^\d+(\.\d+)?$/.test(text) ? Number(text) : Number.NaN
}

const noteOf = (raw: string): string | null => raw.trim() || null

export function buildWeightPatch(fields: { date: string; kg: string; note: string }): { date: string; weight_kg: number; note: string | null } | null {
  const kg = typed(fields.kg)
  if (fields.date === '' || kg === null || !(kg > 0)) return null
  // An emptied note is sent as null: that is what clears it.
  return { date: fields.date, weight_kg: kg, note: noteOf(fields.note) }
}

export interface MeasureBody {
  date: string
  neck_cm: number | null
  waist_cm: number | null
  hips_cm: number | null
  note: string | null
}

/** The whole row of a tape measurement: a circumference left empty is `null`, which on an
 *  edit removes the value that was there. */
export function buildMeasureBody(fields: { date: string; neck: string; waist: string; hips: string; note: string }): MeasureBody | null {
  const [neck, waist, hips] = [typed(fields.neck), typed(fields.waist), typed(fields.hips)]
  if (fields.date === '' || [neck, waist, hips].some((v) => Number.isNaN(v))) return null
  return { date: fields.date, neck_cm: neck, waist_cm: waist, hips_cm: hips, note: noteOf(fields.note) }
}
