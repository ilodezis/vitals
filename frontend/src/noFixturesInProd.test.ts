import { describe, expect, it } from 'vitest'

const prodSources = import.meta.glob<string>(
  [
    '/src/**/*.{ts,tsx}',
    '!/src/fixtures/**',
    '!/src/**/*.test.{ts,tsx}',
    '!/src/**/*.d.ts',
    '!/src/routeTree.gen.ts',
  ],
  {
    query: '?raw',
    import: 'default',
    eager: true,
  },
)

describe('noFixturesInProd', () => {
  it('ensures no production file imports from @/fixtures or uses FIXTURE_TODAY', () => {
    const entries = Object.entries(prodSources)
    expect(entries.length).toBeGreaterThan(20)
    const offenders = entries
      .filter(
        ([, content]) =>
          /from\s+['"]@\/fixtures/.test(content) ||
          /from\s+['"][.\/]+fixtures/.test(content) ||
          /\bFIXTURE_TODAY\b/.test(content) ||
          /\bFIXTURE_NOW\b/.test(content),
      )
      .map(([file]) => file)
    expect(offenders).toEqual([])
  })
})
