export interface HrtCyclePlanItem {
  id: number
  compoundKey: string
  name: string
  dose: number
  unit: string
  every?: number | null
  from: number
  durationDays?: number | null
  /** False for a ramp or a schedule of several segments: only its start week is edited. */
  flat?: boolean
  note?: string | null
}

export interface HrtActiveCycle {
  id: number
  kind: string
  name: string
  start: string
  end?: string | null
  note?: string | null
  cadence: number
  week: number
  weeks?: number | null
  pct?: number | null
  items: HrtCyclePlanItem[]
}

export interface HrtDoseItem {
  id: number
  date: string
  name: string
  compoundKey: string
  dose: string
  doseVal: number
  unit: string
  ml?: number | null
  concMgMl?: number | null
  brand?: string | null
  lab?: string | null
  batch?: string | null
  site?: string | null
  note?: string | null
}

export interface HrtSideEffectItem {
  id: number
  date: string
  name: string
  sev: number
  note?: string | null
}

export interface HrtTemplateItem {
  id: number
  name: string
  kind: string
  /** Each compound's name and the whole weeks after the start it begins (0 = from the start). */
  items: [string, number][]
  exportJson: string
}

export interface HrtPlannedItem {
  date: string
  name: string
  compoundKey: string
  dose: string
  doseVal?: number | null
  unit: string
}

export interface HrtCompoundItem {
  id: number
  key: string
  name: string
  compoundClass?: string | null
  ester?: string | null
  route?: string | null
  doseUnit?: string | null
  concMgMl?: number | null
}

export interface HrtLastDose {
  date: string
  name: string
  dose: string
}

export interface HrtView {
  cycle?: HrtActiveCycle | null
  doses: HrtDoseItem[]
  sideEffects: HrtSideEffectItem[]
  templates: HrtTemplateItem[]
  planned: HrtPlannedItem[]
  release: { date: string; total_mg: number; by_class?: Record<string, number> }[]
  catalog: number
  compounds: HrtCompoundItem[]
  siteLabels: Record<string, string>
  siteCounts: Record<string, number>
  last?: HrtLastDose | null
  /** The dose units and the cycle kinds the service accepts. */
  units: string[]
  cycleKinds: string[]
}
