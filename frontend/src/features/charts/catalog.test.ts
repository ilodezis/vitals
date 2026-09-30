import { describe, expect, it } from 'vitest'
import { emptySeries, metricOf, metricOptionLabel, needsParam, pickDomain, pickMetric, readCatalog, rowReady, seriesBody } from './catalog'

const raw = {
  weight: {
    label: 'Weight',
    metrics: [
      { key: 'ma', label: 'Weight (7-day average)', unit: 'kg', param_kind: 'none' },
      { key: 'raw', label: 'Weight', unit: 'kg', param_kind: 'none' },
    ],
  },
  labs: {
    label: 'Labs',
    metrics: [{ key: 'lab_marker', label: 'Lab marker', unit: null, param_kind: 'labs_marker', params: [{ value: 'TSH', label: 'TSH' }] }],
  },
}

describe('chart catalog', () => {
  const domains = readCatalog(raw)

  it('reads domains and metrics in the server order', () => {
    expect(domains.map((d) => d.key)).toEqual(['weight', 'labs'])
    expect(domains[0]?.metrics.map((m) => m.key)).toEqual(['ma', 'raw'])
  })

  it('names a metric with its unit, and a unitless one alone', () => {
    const ma = metricOf(domains, 'weight', 'ma')
    const lab = metricOf(domains, 'labs', 'lab_marker')
    expect(ma && metricOptionLabel(ma)).toBe('Weight (7-day average) (kg)')
    expect(lab && metricOptionLabel(lab)).toBe('Lab marker')
  })

  it('asks for a parameter only where the metric needs one', () => {
    expect(needsParam(metricOf(domains, 'weight', 'ma'))).toBe(false)
    expect(needsParam(metricOf(domains, 'labs', 'lab_marker'))).toBe(true)
  })

  it('clears what depends on a changed choice', () => {
    const row = { domain: 'labs', metricKey: 'lab_marker', param: 'TSH' }
    expect(pickDomain(row, 'weight')).toEqual({ domain: 'weight', metricKey: '', param: '' })
    expect(pickDomain(row, 'labs')).toBe(row)
    expect(pickMetric(row, 'other')).toEqual({ domain: 'labs', metricKey: 'other', param: '' })
  })

  it('is ready only with a known metric and its parameter', () => {
    expect(rowReady(domains, emptySeries())).toBe(false)
    expect(rowReady(domains, { domain: 'weight', metricKey: 'ma', param: '' })).toBe(true)
    expect(rowReady(domains, { domain: 'labs', metricKey: 'lab_marker', param: '' })).toBe(false)
    expect(rowReady(domains, { domain: 'labs', metricKey: 'lab_marker', param: 'TSH' })).toBe(true)
    expect(rowReady(domains, { domain: 'weight', metricKey: 'unknown', param: '' })).toBe(false)
  })

  it('sends a parameter only for a metric that takes one', () => {
    expect(seriesBody(domains, { domain: 'weight', metricKey: 'ma', param: 'stale' })).toEqual({ domain: 'weight', metricKey: 'ma', param: null })
    expect(seriesBody(domains, { domain: 'labs', metricKey: 'lab_marker', param: 'TSH' })).toEqual({ domain: 'labs', metricKey: 'lab_marker', param: 'TSH' })
  })
})
