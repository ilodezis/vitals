/* The chart builder's pickers, read from `ChartsView.catalog`: the server lists the domains the
   enabled modules allow, each domain's metrics with their unit, and — for a metric that needs one
   (a lab marker, an exercise, a body-scan metric) — the parameters to choose from. */

export interface CatalogParam {
  value: string
  label: string
}

export interface CatalogMetric {
  key: string
  label: string
  unit: string | null
  paramKind: string
  params: CatalogParam[]
}

export interface CatalogDomain {
  key: string
  label: string
  metrics: CatalogMetric[]
}

export interface SeriesDraft {
  domain: string
  metricKey: string
  param: string
}

export const MAX_SERIES = 8

export const emptySeries = (): SeriesDraft => ({ domain: '', metricKey: '', param: '' })

const str = (v: unknown): string => (typeof v === 'string' ? v : '')

function readParams(raw: unknown): CatalogParam[] {
  if (!Array.isArray(raw)) return []
  return raw
    .map((p: unknown) => {
      const o = (p ?? {}) as Record<string, unknown>
      const value = str(o.value)
      return { value, label: str(o.label) || value }
    })
    .filter((p) => p.value !== '')
}

function readMetric(raw: unknown): CatalogMetric | null {
  const o = (raw ?? {}) as Record<string, unknown>
  const key = str(o.key)
  if (key === '') return null
  const unit = str(o.unit)
  return {
    key,
    label: str(o.label) || key,
    unit: unit === '' ? null : unit,
    paramKind: str(o.param_kind) || 'none',
    params: readParams(o.params),
  }
}

/** The catalog as the pickers draw it, in the server's order. */
export function readCatalog(catalog: Record<string, unknown>): CatalogDomain[] {
  return Object.entries(catalog).map(([key, raw]) => {
    const o = (raw ?? {}) as Record<string, unknown>
    const list = Array.isArray(o.metrics) ? o.metrics : Object.values((o.metrics ?? {}) as Record<string, unknown>)
    return {
      key,
      label: str(o.label) || key,
      metrics: list.map(readMetric).filter((m): m is CatalogMetric => m !== null),
    }
  })
}

export const metricsOf = (domains: readonly CatalogDomain[], domain: string): CatalogMetric[] =>
  domains.find((d) => d.key === domain)?.metrics ?? []

export const metricOf = (domains: readonly CatalogDomain[], domain: string, metricKey: string): CatalogMetric | undefined =>
  metricsOf(domains, domain).find((m) => m.key === metricKey)

/** A metric that is read per lab marker, exercise or scan metric asks for that choice too. */
export const needsParam = (metric: CatalogMetric | undefined): boolean => metric !== undefined && metric.paramKind !== 'none'

/** "Weight (kg)" — how the metric picker names a metric. */
export const metricOptionLabel = (m: CatalogMetric): string => (m.unit === null ? m.label : `${m.label} (${m.unit})`)

/** A new domain clears the metric and parameter; a new metric clears the parameter. */
export function pickDomain(row: SeriesDraft, domain: string): SeriesDraft {
  return domain === row.domain ? row : { domain, metricKey: '', param: '' }
}

export function pickMetric(row: SeriesDraft, metricKey: string): SeriesDraft {
  return metricKey === row.metricKey ? row : { ...row, metricKey, param: '' }
}

/** A row is ready when its domain and metric exist in the catalog and a parameter is chosen
 *  where the metric needs one. */
export function rowReady(domains: readonly CatalogDomain[], row: SeriesDraft): boolean {
  const metric = metricOf(domains, row.domain, row.metricKey)
  if (metric === undefined) return false
  if (!needsParam(metric)) return true
  return metric.params.some((p) => p.value === row.param)
}

/** What the API is sent for a row: the parameter only where the metric takes one. */
export function seriesBody(domains: readonly CatalogDomain[], row: SeriesDraft): { domain: string; metricKey: string; param: string | null } {
  const metric = metricOf(domains, row.domain, row.metricKey)
  return { domain: row.domain, metricKey: row.metricKey, param: needsParam(metric) && row.param !== '' ? row.param : null }
}
