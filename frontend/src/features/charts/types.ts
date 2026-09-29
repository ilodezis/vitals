export interface ChartPoint {
  date: string
  value: number
}

export interface ChartResolvedSeries {
  label: string
  unit?: string | null
  colorSlot: number
  points: ChartPoint[]
}

export interface ChartOverlay {
  start: string
  end?: string | null
  label: string
  tone: string
  kind: string
}

export interface CustomChartItem {
  id: string
  name: string
  normalize: boolean
  series: ChartResolvedSeries[]
  overlays: ChartOverlay[]
}

export interface ChartCatalogMetric {
  key?: string
  label?: string
  params?: string[]
  [key: string]: unknown
}

export interface ChartCatalogDomain {
  label?: string
  metrics?: Record<string, ChartCatalogMetric> | ChartCatalogMetric[]
  [key: string]: unknown
}

export interface ChartsView {
  charts: CustomChartItem[]
  catalog: Record<string, ChartCatalogDomain>
  count: number
  empty: boolean
}

export interface ChartSeriesInput {
  domain: string
  metricKey: string
  param?: string | null
  label?: string | null
}
