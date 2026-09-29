export interface MilestoneItem {
  id: number
  name: string
  domain: string
  status: string
  targetValue?: number | null
  targetUnit?: string | null
  deadline?: string | null
  daysLeft?: number | null
  current?: number | null
  remaining?: number | null
  pct?: number | null
  closedOn?: string | null
  deadlineMarginDays?: number | null
}

export interface DigestItem {
  id: number
  date?: string | null
  kind: string
  content: string
  model?: string | null
  periodStart?: string | null
  periodEnd?: string | null
  createdAt?: string | null
}

export interface ReportsView {
  activeGoals: MilestoneItem[]
  closedGoals: MilestoneItem[]
  activeGoalsCount: number
  closedGoalsCount: number
  latestDigest?: DigestItem | null
  digestHistory: DigestItem[]
  digestsCount: number
  latestBrief?: DigestItem | null
  goalDomains: string[]
  llmConfigured: boolean
  channelConfigured: boolean
  today: string
}
