export interface ConflictRuleItem {
  id: number
  code?: string | null
  ruleType: string
  type: string
  domainA: string
  domainB: string
  a: string
  b: string
  severity: string
  sev: string
  message: string
  msg: string
  category: string
  cat: string
  source?: string | null
  src?: string | null
  evidence?: string | null
  ev?: string | null
  active: boolean
  on: boolean
  firing: boolean
  hours?: number | null
  h?: number | null
}

export interface InteractionsView {
  rules: ConflictRuleItem[]
  byCategory: Record<string, ConflictRuleItem[]>
  orderedCategories: string[]
  firingIds: number[]
  allDomains: string[]
  totalCount: number
  firingCount: number
}
