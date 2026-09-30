import type { components } from '@/api/schema'

type BodyScanMetricItem = components['schemas']['BodyScanMetricItem']

/** A recognised metric while it is being checked: its value is the text in the field, so a
 *  cleared or half-typed field stays what it is instead of turning into 0. */
export type ScanPreviewMetric = Omit<BodyScanMetricItem, 'value'> & { value: string }

export function toScanPreview(metrics: BodyScanMetricItem[]): ScanPreviewMetric[] {
  return metrics.map((metric) => ({ ...metric, value: String(metric.value) }))
}

/** The rows as the server takes them, or `null` when any value is not a number: the scan is
 *  not saved with a value nobody entered. */
export function readScanMetrics(rows: ScanPreviewMetric[]): BodyScanMetricItem[] | null {
  const metrics: BodyScanMetricItem[] = []
  for (const row of rows) {
    const text = row.value.trim().replace(',', '.')
    if (!/^-?\d+(\.\d+)?$/.test(text)) return null
    metrics.push({ ...row, value: Number(text) })
  }
  return metrics
}

/** The order a scan's metrics are read in, by category; anything else goes under "other". */
export const SCAN_CATEGORIES = ['composition', 'water', 'segmental', 'score', 'derived', 'other'] as const

/** A saved scan's metrics grouped by category, in the order above; an empty group is left out. */
export function groupScanMetrics(metrics: readonly BodyScanMetricItem[]): { category: string; metrics: BodyScanMetricItem[] }[] {
  const known = new Set<string>(SCAN_CATEGORIES)
  return SCAN_CATEGORIES.map((category) => ({
    category,
    metrics: metrics.filter((m) => {
      const c = m.category ?? 'other'
      return category === 'other' ? !known.has(c) || c === 'other' : c === category
    }),
  })).filter((g) => g.metrics.length > 0)
}

/** "3,5–5,0": a metric's reference range; either end may be missing, both missing is no range. */
export function scanRefText(m: Pick<BodyScanMetricItem, 'ref_low' | 'ref_high'>, fmt: (v: number) => string): string | null {
  if (m.ref_low == null && m.ref_high == null) return null
  return `${m.ref_low == null ? '' : fmt(m.ref_low)}–${m.ref_high == null ? '' : fmt(m.ref_high)}`
}
