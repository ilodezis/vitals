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
