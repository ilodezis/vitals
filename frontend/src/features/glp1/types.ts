/** Where an injection can go. The body map draws them; the API names them the same way. */
export type SiteId =
  | 'shoulder_left' | 'shoulder_right'
  | 'abdomen_left' | 'abdomen_right'
  | 'thigh_left' | 'thigh_right'

export interface Injection {
  dateIso: string
  /** Null for an entry that was logged without a site. */
  site: SiteId | null
  doseMg: number
}

/** `GET /api/v1/glp1`. What the server does not have yet — no injection logged — stays `null`:
 *  the screen prints a dash, never a likely dose. */
export interface Glp1View {
  drug: string | null
  doseMg: number | null
  sinceIso: string | null
  /** Days on the current dose, counting the first. */
  dayOnDose: number | null
  /** Weight change since the current dose began; null with fewer than two weigh-ins. */
  deltaOnDoseKg: number | null
  cycle: {
    lastIso: string | null
    nextIso: string | null
    /** Negative when the injection is overdue. */
    daysToNext: number | null
    overdue: boolean
    unscheduled: boolean
  }
  /** Steps of the dose over time, oldest first, and the weight trend under them. */
  dosePhases: { fromIso: string; toIso: string; doseMg: number }[]
  trend: { date: string; kg: number }[]
  /** Site names in the user's language. */
  siteLabels: Record<string, string>
  /** Newest first. */
  injections: Injection[]
  sideEffects: { dateIso: string; name: string; severity: 1 | 2 | 3 | 4 | 5 }[]
}
