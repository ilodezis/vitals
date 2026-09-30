/** Bodies of the GLP-1 forms on the screen. A form that does not hold a whole entry is `null`
 *  and stays unsaved: no dose is ever recorded that the person did not type. */

/** The drugs the forms offer by name; the server accepts any. */
const KNOWN_DRUGS = ['semaglutide', 'tirzepatide'] as const

/** What the drug field offers: the known ones, and the entry's own drug when it is another. */
export function drugOptions(current: string | null): string[] {
  const known: string[] = [...KNOWN_DRUGS]
  return current === null || current === '' || known.includes(current) ? known : [...known, current]
}

function positive(raw: string): number | null {
  const text = raw.trim().replace(',', '.')
  if (!/^\d+(\.\d+)?$/.test(text)) return null
  const value = Number(text)
  return value > 0 ? value : null
}

export interface InjectionPatch {
  date: string
  doseMg: number
  drug: string
  site: string | null
  note: string | null
}

/** The whole injection as the edit form holds it: a site or a note taken off is `null`,
 *  which removes it. */
export function buildInjectionPatch(fields: { date: string; dose: string; drug: string; site: string | null; note: string }): InjectionPatch | null {
  const doseMg = positive(fields.dose)
  const drug = fields.drug.trim()
  if (fields.date === '' || drug === '' || doseMg === null) return null
  return { date: fields.date, doseMg, drug, site: fields.site, note: fields.note.trim() || null }
}

export interface PhaseBody {
  startDate: string
  endDate: string | null
  drug: string
  doseMg: number
}

/** A new dose phase. Without an end date it is the running one. */
export function buildPhaseBody(fields: { start: string; end: string; drug: string; dose: string }): PhaseBody | null {
  const doseMg = positive(fields.dose)
  const drug = fields.drug.trim()
  if (fields.start === '' || drug === '' || doseMg === null) return null
  // ISO dates compare as text.
  if (fields.end !== '' && fields.end < fields.start) return null
  return { startDate: fields.start, endDate: fields.end === '' ? null : fields.end, drug, doseMg }
}
