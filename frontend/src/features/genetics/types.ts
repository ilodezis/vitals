export interface GeneticVariantItem {
  id: number
  gene: string
  rsid?: string | null
  genotype?: string | null
  gt?: string | null
  marker?: string | null
  impact?: string | null
  impactDomain?: string | null
  dom?: string | null
  interpretation?: string | null
  interp?: string | null
  actionNotes?: string | null
  action?: string | null
  source?: string | null
  hasRisk: boolean
}

export interface GeneticsView {
  variants: GeneticVariantItem[]
  count: number
  empty: boolean
}
