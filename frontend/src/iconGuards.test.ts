import { describe, expect, it } from 'vitest'

const iconCss = import.meta.glob<string>('/src/components/icons/icon.css', { query: '?raw', import: 'default', eager: true })

const featureSources = import.meta.glob<string>(['/src/features/**/*.{ts,tsx,css}', '!/src/**/*.test.{ts,tsx}'], {
  query: '?raw',
  import: 'default',
  eager: true,
})

describe('icons keep one size and one collapsible arrow', () => {
  const css = Object.values(iconCss)[0] ?? ''

  it('gives every icon a base size of one em, and stops it from shrinking in a flex row', () => {
    expect(css).toMatch(/\.icon\s*\{[^}]*\bflex:\s*none\b/)
    // Zero specificity, so a parent's own size always wins.
    expect(css).toMatch(/:where\(\.icon\)\s*\{[^}]*\bwidth:\s*1em\b[^}]*\bheight:\s*1em\b/)
  })

  it('leaves the collapsible arrow to the Disclosure: no chevD / chevR switch of a screen’s own', () => {
    const entries = Object.entries(featureSources)
    expect(entries.length).toBeGreaterThan(20)
    const offenders = entries.filter(([, source]) => /chevD['"`]?\s*:\s*['"`]chevR|chevR['"`]?\s*:\s*['"`]chevD/.test(source)).map(([file]) => file)
    expect(offenders).toEqual([])
  })

  it('has no rot-180 class: nothing defines it, so nothing turns', () => {
    const offenders = Object.entries(featureSources)
      .filter(([, source]) => source.includes('rot-180'))
      .map(([file]) => file)
    expect(offenders).toEqual([])
  })
})
