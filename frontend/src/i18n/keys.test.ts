import { describe, expect, it } from 'vitest'
import en from './en.json'
import ru from './ru.json'

/* Every string key the screens ask for has to exist in both dictionaries. A key that is only
   missing from one language shows up in the UI as the raw key, and nothing else notices. */

const dictionaries: Record<string, Record<string, string>> = { en, ru }

const sources = import.meta.glob<string>(['/src/**/*.{ts,tsx}', '!/src/**/*.test.{ts,tsx}', '!/src/**/*.d.ts', '!/src/routeTree.gen.ts'], {
  query: '?raw',
  import: 'default',
  eager: true,
})

// 'app.today.entries.one' in any quotes, wherever it stands: a `t('…')` call or a key held in a table.
const LITERAL = /(['"`])(app\.[a-z0-9_]+(?:\.[a-z0-9_]+)+)\1/g
// `app.labs.status.${status}` — only the fixed front of the key can be checked.
const TEMPLATE = /`(app\.[a-z0-9_.]*\.)\$\{/g

export function keysIn(source: string): { literals: string[]; prefixes: string[] } {
  return {
    literals: [...source.matchAll(LITERAL)].map((m) => m[2] as string),
    prefixes: [...source.matchAll(TEMPLATE)].map((m) => m[1] as string),
  }
}

describe('keysIn', () => {
  it('finds a key however it is quoted', () => {
    expect(keysIn(`t('app.a.b') + t("app.c.d.e") + t(\`app.f.g\`)`).literals).toEqual(['app.a.b', 'app.c.d.e', 'app.f.g'])
  })

  it('finds the front of a key built from a value', () => {
    expect(keysIn('t(`app.labs.status.${state}`)').prefixes).toEqual(['app.labs.status.'])
  })

  it('leaves alone what merely looks like a file or a word', () => {
    expect(keysIn(`import './app.css'; const s = 'app.css'; const w = 'the app.'`)).toEqual({ literals: [], prefixes: [] })
  })
})

describe('string keys used by the screens', () => {
  const used = Object.entries(sources).map(([file, text]) => ({ file, ...keysIn(text) }))

  it('actually scans the source', () => {
    expect(used.length).toBeGreaterThan(20)
    expect(used.flatMap((u) => u.literals).length).toBeGreaterThan(100)
  })

  for (const [lang, dictionary] of Object.entries(dictionaries)) {
    it(`has every literal key in the ${lang} dictionary`, () => {
      const missing = used.flatMap((u) => u.literals.filter((key) => !(key in dictionary)).map((key) => `${u.file}: ${key}`))
      expect(missing).toEqual([])
    })

    it(`has keys behind every built key prefix in the ${lang} dictionary`, () => {
      const names = Object.keys(dictionary)
      const orphaned = used.flatMap((u) => u.prefixes.filter((p) => !names.some((k) => k.startsWith(p))).map((p) => `${u.file}: ${p}`))
      expect(orphaned).toEqual([])
    })
  }

  it('keeps the two dictionaries on the same keys', () => {
    expect(Object.keys(ru).sort()).toEqual(Object.keys(en).sort())
  })
})
