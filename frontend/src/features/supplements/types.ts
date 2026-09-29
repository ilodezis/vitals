export interface SupplementItem {
  id: number
  name: string
  key: string
  dose?: string | null
  timing?: string | null
  timingSlot?: string | null
  timingBucket?: string | null
  evidence?: string | null
  active: boolean
  contraindications?: string | null
  contra?: string | null
  note?: string | null
}

export interface SupplementGroup {
  key: string
  label: string
  sub: string
  tone: string
  items: SupplementItem[]
}

export interface SupplementsView {
  groups: SupplementGroup[]
  active: SupplementItem[]
  archived: SupplementItem[]
  activeCount: number
  totalCount: number
}
