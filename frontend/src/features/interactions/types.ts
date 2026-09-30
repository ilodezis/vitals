export interface ConflictRuleItem {
  id: number
  code?: string | null
  ruleType: string
  domainA: string
  domainB: string
  severity: string
  message: string
  category: string
  source?: string | null
  evidence?: string | null
  active: boolean
  firing: boolean
  hours?: number | null
}

export interface InteractionsView {
  rules: ConflictRuleItem[]
  orderedCategories: string[]
  firingIds: number[]
  allDomains: string[]
  totalCount: number
  firingCount: number
}
