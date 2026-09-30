import { describe, expect, it } from 'vitest'
import { groupScanMetrics, readScanMetrics, scanRefText, toScanPreview } from './scanMetrics'

describe('scan preview metrics', () => {
  it('round-trips the recognised values', () => {
    const recognised = [
      { label: 'Body fat', value: 18.4, unit: '%' },
      { label: 'Visceral fat', value: 0, unit: '' },
    ]
    expect(readScanMetrics(toScanPreview(recognised))).toEqual(recognised)
  })

  it('reads a corrected value, with a comma or a dot', () => {
    expect(readScanMetrics([{ label: 'Muscle', value: '41,7', unit: 'kg' }])).toEqual([
      { label: 'Muscle', value: 41.7, unit: 'kg' },
    ])
    expect(readScanMetrics([{ label: 'Muscle', value: ' 41.7 ', unit: 'kg' }])).toEqual([
      { label: 'Muscle', value: 41.7, unit: 'kg' },
    ])
  })

  it('refuses the whole scan when a value is empty or not a number, instead of saving 0', () => {
    const fine = { label: 'Body fat', value: '18.4', unit: '%' }
    for (const value of ['', '  ', 'abc', '12.', '1e3']) {
      expect(readScanMetrics([fine, { label: 'New metric', value, unit: '' }])).toBeNull()
    }
  })
})

describe('saved scan detail', () => {
  const metric = (label: string, category: string | null) => ({ label, value: 1, category })

  it('groups the metrics by category in reading order, unknown ones under other', () => {
    const groups = groupScanMetrics([metric('a', 'water'), metric('b', 'composition'), metric('c', 'mystery'), metric('d', null), metric('e', 'water')])
    expect(groups.map((g) => [g.category, g.metrics.map((m) => m.label)])).toEqual([
      ['composition', ['b']],
      ['water', ['a', 'e']],
      ['other', ['c', 'd']],
    ])
  })

  it('prints a one-sided reference as a limit, not as a range with a hole', () => {
    const fmt = (v: number) => String(v)
    expect(scanRefText({ ref_low: 3.5, ref_high: 5 }, fmt)).toBe('3.5–5')
    // "–5" reads as minus five
    expect(scanRefText({ ref_low: null, ref_high: 5 }, fmt)).toBe('≤ 5')
    expect(scanRefText({ ref_low: 3.5, ref_high: null }, fmt)).toBe('≥ 3.5')
    expect(scanRefText({ ref_low: null, ref_high: null }, fmt)).toBeNull()
  })
})
