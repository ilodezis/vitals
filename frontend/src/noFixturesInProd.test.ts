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

  /* A screen that cannot read its data says so (the boundary around it); it does not fill the gap
     with a plausible person. These are the stand-ins the screens used to carry. */
  const STUBS: { what: string; pattern: RegExp }[] = [
    { what: 'a made-up weight goal', pattern: /\btargetKg:\s*80\b/ },
    { what: 'a made-up height', pattern: /\?\?\s*190\b/ },
    { what: 'a made-up sex', pattern: /\?\?\s*['"]male['"]/ },
    { what: 'an EMPTY_ stand-in object', pattern: /\bEMPTY_[A-Z0-9_]+\b/ },
    { what: 'a default…View stand-in object', pattern: /\bdefault[A-Z][A-Za-z]*View\b/ },
    { what: 'default norms', pattern: /\bDEFAULT_NORMS\b/ },
    { what: 'an unread request handed back as an empty view', pattern: /data\s*\?\?\s*(?:default|EMPTY)/ },
  ]

  for (const { what, pattern } of STUBS) {
    it(`has no production file with ${what}`, () => {
      const offenders = Object.entries(prodSources)
        .filter(([, content]) => pattern.test(content))
        .map(([file]) => file)
      expect(offenders).toEqual([])
    })
  }

  /* `parseInt(text) || 30` saves 30 over a field the person cleared, and over a typed 0. A form
     reads its fields through a function that can answer "not a number". */
  it('has no feature reading a field with a number to fall back on', () => {
    const features = Object.entries(prodSources).filter(([file]) => file.startsWith('/src/features/'))
    expect(features.length).toBeGreaterThan(20)
    const offenders = features
      .filter(([, content]) => /\bparse(?:Int|Float)\([^()]*\)\s*\|\|\s*-?\d/.test(content))
      .map(([file]) => file)
    expect(offenders).toEqual([])
  })

  it('has every use…View hook read its screen suspending, so that a failed read reaches the boundary', () => {
    const hooks = Object.entries(prodSources).filter(([file]) => /\/features\/[a-z0-9]+\/use[A-Za-z]+View\.ts$/.test(file))
    expect(hooks.length).toBeGreaterThan(10)
    const swallowing = hooks
      // The more list is a side card: it may fill in as it arrives.
      .filter(([file]) => !file.endsWith('/more/useMoreView.ts'))
      .filter(([, content]) => !content.includes('useSuspenseQuery') || /\bcatch\b/.test(content))
      .map(([file]) => file)
    expect(swallowing).toEqual([])
  })

  it('calls the API only through its typed client: no `(api as any)`', () => {
    const offenders = Object.entries(prodSources)
      .filter(([, content]) => /\(api as any\)/.test(content))
      .map(([file]) => file)
    expect(offenders).toEqual([])
  })
})
