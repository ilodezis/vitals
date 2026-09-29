export interface TimelineEventItem {
  id?: number | null
  date: string
  endDate?: string | null
  domain: string
  dom: string
  kind: string
  title: string
  detail?: string | null
  tone: string
  source: string
  manual: boolean
  ref: string
}

export interface AnnotationCreate {
  title: string
  date: string
  endDate?: string | null
  kind?: string
  domain?: string
  note?: string | null
}

export interface TimelineView {
  events: TimelineEventItem[]
  manualCount: number
  totalCount: number
  domains: string[]
  kinds: string[]
  today: string
}
