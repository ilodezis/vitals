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

export interface DoseBody {
  dose?: number
  volumeMl?: number
  concentrationMgMl?: number
}

/** The amount of a dose: typed in the compound's unit, or drawn from a vial — a volume and the
 *  vial's concentration (or the catalog's typical one), which the service turns into mg. */
export function buildDoseBody(fields: { dose: string; volume?: string; concentration?: string; catalogConcentration?: number | null }): DoseBody | null {
  const dose = positive(fields.dose)
  const volumeMl = positive(fields.volume ?? '')
  const concentrationMgMl = positive(fields.concentration ?? '')
  const body: DoseBody = {}
  if (dose !== null) body.dose = dose
  if (volumeMl !== null) body.volumeMl = volumeMl
  if (concentrationMgMl !== null) body.concentrationMgMl = concentrationMgMl
  if (dose !== null) return body
  const knownConcentration = concentrationMgMl ?? (fields.catalogConcentration != null && fields.catalogConcentration > 0 ? fields.catalogConcentration : null)
  return volumeMl !== null && knownConcentration !== null ? body : null
}

export interface CompoundGroup<T> {
  cls: string
  items: T[]
}

/** The catalog grouped by class, in the order the classes first appear. */
export function groupByClass<T extends { compoundClass?: string | null }>(compounds: readonly T[]): CompoundGroup<T>[] {
  const groups: CompoundGroup<T>[] = []
  for (const c of compounds) {
    const cls = c.compoundClass ?? ''
    let group = groups.find((g) => g.cls === cls)
    if (group === undefined) {
      group = { cls, items: [] }
      groups.push(group)
    }
    group.items.push(c)
  }
  return groups
}

/** A release series' index of today, or null when today is outside it. */
export function todayIndex(series: readonly { date: string }[], todayIso: string): number | null {
  const i = series.findIndex((p) => p.date === todayIso)
  return i < 0 ? null : i
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

interface DrugAndUnit {
  compoundKey: string
  unit: string
}

/** The drug a new dose starts on: the one injected last, else the first of the running course,
 *  else none, so the form asks. Never the top of the catalog, which is only first by name. */
export function startingDrug(view: { doses: readonly DrugAndUnit[]; cycle?: { items: readonly DrugAndUnit[] } | null }): DrugAndUnit {
  const from = view.doses[0] ?? view.cycle?.items[0]
  return from ? { compoundKey: from.compoundKey, unit: from.unit } : { compoundKey: '', unit: 'mg' }
}
