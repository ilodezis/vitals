/** Where an injection can go. The body map draws them; the API names them the same way. */
export type SiteId =
  | 'shoulder_left' | 'shoulder_right'
  | 'abdomen_left' | 'abdomen_right'
  | 'thigh_left' | 'thigh_right'

export interface Injection {
  dateIso: string
  site: SiteId
  doseMg: number
}

/** `GET /api/v1/glp1`. */
export interface Glp1View {
  drug: string
  doseMg: number
  sinceIso: string
  /** Days on the current dose, counting the first. */
  dayOnDose: number
  cycle: { lastIso: string; nextIso: string; daysToNext: number; unscheduled: boolean }
  /** Steps of the dose over time, oldest first, and the weight trend under them. */
  dosePhases: { fromIso: string; toIso: string; doseMg: number }[]
  trend: { date: string; kg: number }[]
  /** A generated sentence about how the weight moved on each dose. */
  summary: string
  /** Sites in the order they were used most recently first; the map dims older ones. */
  siteLabels: Record<SiteId, string>
  injections: Injection[]
  sideEffects: { dateIso: string; name: string; severity: 1 | 2 | 3 | 4 | 5 }[]
}
