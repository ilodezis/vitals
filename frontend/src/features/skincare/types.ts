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
}
