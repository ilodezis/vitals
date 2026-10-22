export interface SkincareProductItem {
  id: number
  name: string
  type: string
  activeIngredient?: string | null
  ing?: string | null
  description?: string | null
  desc?: string | null
  usageInstructions?: string | null
  use?: string | null
  defaultTime: string
  time: string
  scheduleDays: number[]
  days: number[]
  active: boolean
  on: boolean
  default_time?: string
  schedule_days?: number[]
  usage_instructions?: string | null
  /** The conflict-engine flag a tick on this product sets; null = none the rules know. */
  activeFlag?: string | null
}

export interface SkincareLogItem {
  id: number
  date: string
  retinoid: boolean
  azelaic: boolean
  peel: boolean
  niacinamideSpf: boolean
  moisturizer: boolean
  vitaminC: boolean
  benzoylPeroxide: boolean
  note?: string | null
}

export interface SkincareObservationItem {
  id: number
  date: string
  inflammation?: number | null
  inf?: number | null
  pih?: number | null
  zone?: string | null
  note?: string | null
}

export interface SkincareRuleItem {
  id: number
  code?: string | null
  severity: string
  sev: string
  kind: string
  msg: string
  hard: boolean
}

export interface SkincareAlertItem {
  id: number
  domain: string
  severity: string
  alertKey: string
  message: string
  createdAt?: string | null
}

/** One product in one slot of a day, and whether it was done. */
export interface SkincarePlanItem {
  /** Null once the product was deleted from the catalog — its tick is history. */
  productId: number | null
  name: string
  flag: string | null
  /** False for a tick on a product that was not scheduled that day. */
  planned: boolean
  done: boolean
  doneAt: string | null
}

export interface SkincareDayPlan {
  morning: SkincarePlanItem[]
  evening: SkincarePlanItem[]
}

export interface SkincareHistoryDay extends SkincareDayPlan {
  date: string
}

export interface SkincarePhotoItem {
  id: number
  date: string
  url: string
  thumbUrl: string
  screenUrl: string
  note?: string | null
}

export interface SkincareView {
  products: SkincareProductItem[]
  activeCount: number
  totalCount: number
  todayLog?: SkincareLogItem | null
  logs: SkincareLogItem[]
  observations: SkincareObservationItem[]
  rules: SkincareRuleItem[]
  alerts: SkincareAlertItem[]
  today: string
  plan: SkincareDayPlan
  /** Newest first, today excluded, starting no earlier than the first tick. */
  history: SkincareHistoryDay[]
  photos: SkincarePhotoItem[]
  /** The flags a product can be mapped to. */
  flags: string[]
}
