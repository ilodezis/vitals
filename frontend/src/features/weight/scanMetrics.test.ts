import { describe, expect, it } from 'vitest'
import { readScanMetrics, toScanPreview } from './scanMetrics'

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
