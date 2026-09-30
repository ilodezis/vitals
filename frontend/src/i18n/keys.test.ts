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

/* ---------- Any namespace, the placeholders, and the `t(key) || fallback` trap ---------- */

const namespaces = [...new Set(Object.keys(en).map((key) => key.split('.')[0] as string))]
// A key of any namespace that a `t(…)` / `tOr(…)` call asks for, or that a table holds as a plain
// string ('nav.today'). File names that share a namespace's word (settings.css) are not keys.
const CALL_LITERAL = /(?<![\w.])(?:t|tOr)\(\s*(['"`])([a-z_]\w*(?:\.\w+)+)\1/g
const TABLE_LITERAL = new RegExp(`(['"\`])((?:${namespaces.join('|')})(?:\\.[a-z0-9_]+)+)\\1`, 'g')
const FILE_NAME = /\.(?:css|ts|tsx|json|svg|png|js|woff2)$/

export function anyNamespaceKeysIn(source: string): string[] {
  const keys = new Set<string>()
  for (const re of [CALL_LITERAL, TABLE_LITERAL]) {
    for (const m of source.matchAll(re)) {
      const key = m[2] as string
      if (!FILE_NAME.test(key)) keys.add(key)
    }
  }
  return [...keys]
}

const CLOSER: Record<string, string> = { '(': ')', '{': '}', '[': ']' }

/** The index of the bracket that closes the one at `open`, skipping over strings and templates. */
function closeOf(source: string, open: number): number {
  const opener = source[open] as string
  const closer = CLOSER[opener] as string
  let depth = 0
  let quote: string | null = null
  for (let i = open; i < source.length; i += 1) {
    const c = source[i] as string
    if (quote !== null) {
      if (c === '\\') i += 1
      else if (c === quote) quote = null
    } else if (c === "'" || c === '"' || c === '`') quote = c
    else if (c === opener) depth += 1
    else if (c === closer) {
      depth -= 1
      if (depth === 0) return i
    }
  }
  return -1
}

/** The names an object literal passes: `{ n: 3, date }` → ['n', 'date']; null when it spreads
 *  something in (the names are then not knowable here). */
function paramNames(literal: string): string[] | null {
  const entries: string[] = []
  let depth = 0
  let start = 1
  for (let i = 1; i < literal.length - 1; i += 1) {
    const c = literal[i] as string
    if ('([{'.includes(c)) depth += 1
    else if (')]}'.includes(c)) depth -= 1
    else if (c === ',' && depth === 0) {
      entries.push(literal.slice(start, i).trim())
      start = i + 1
    }
  }
  entries.push(literal.slice(start, literal.length - 1).trim())
  const named = entries.filter((entry) => entry !== '')
  if (named.some((entry) => entry.startsWith('...'))) return null
  return named.map((entry) => /^['"]?([A-Za-z_]\w*)/.exec(entry)?.[1] ?? entry)
}

/** Every `t('key', { … })` with a literal key and an object literal: the key and the names given. */
export function paramCalls(source: string): { key: string; names: string[] }[] {
  const calls: { key: string; names: string[] }[] = []
  for (const m of source.matchAll(/(?<![\w.])t\(\s*(['"`])([a-z_]\w*(?:\.\w+)+)\1\s*,\s*(?=\{)/g)) {
    const open = (m.index as number) + m[0].length
    const close = closeOf(source, open)
    if (close === -1) continue
    const names = paramNames(source.slice(open, close + 1))
    if (names !== null) calls.push({ key: m[2] as string, names })
  }
  return calls
}

/** The `{name}` / `{name:spec}` placeholders of a string; `{{` and `}}` are literal braces. */
export function placeholdersOf(text: string): string[] {
  return [...text.replaceAll('{{', '').replaceAll('}}', '').matchAll(/\{([A-Za-z_]\w*)(?::[^{}]*)?\}/g)].map((m) => m[1] as string)
}

/** A `t(…)` whose answer is then `||`- or `??`-ed: `t` returns the key itself for a missing one, so
 *  the right-hand side can never run. `tOr(key, fallback)` is the call that means it. */
export function orAfterT(source: string): number[] {
  const lines: number[] = []
  for (const m of source.matchAll(/(?<![\w.])t\(/g)) {
    const close = closeOf(source, (m.index as number) + 1)
    if (close === -1) continue
    if (/^\s*(\|\||\?\?)/.test(source.slice(close + 1, close + 8))) lines.push(source.slice(0, m.index).split('\n').length)
  }
  return lines
}

describe('anyNamespaceKeysIn', () => {
  it('finds keys of every namespace, in calls and in tables, and not file names', () => {
    const source = `t('common.save') + tOr("more.modules", 'x') + { title: 'nav.today' } + import './settings.css'`
    expect(anyNamespaceKeysIn(source).sort()).toEqual(['common.save', 'more.modules', 'nav.today'])
  })
})

describe('paramCalls and placeholdersOf', () => {
  it('reads the names an object literal passes, nested calls and all', () => {
    expect(paramCalls(`t('app.x.y', { n, date: fmt(d, { a: 1 }), 'k': 2 })`)).toEqual([{ key: 'app.x.y', names: ['n', 'date', 'k'] }])
  })

  it('cannot know the names behind a spread', () => {
    expect(paramCalls(`t('app.x.y', { ...rest, n })`)).toEqual([])
  })

  it('lists the placeholders of a string, skipping doubled braces', () => {
    expect(placeholdersOf('{n} of {total:g} {{literal}}')).toEqual(['n', 'total'])
  })
})

describe('orAfterT', () => {
  it('flags a fallback that can never run', () => {
    expect(orAfterT("const a = t('app.x') || 'fallback'\nconst b = t(`app.y.${k}`) ?? k")).toEqual([1, 2])
  })

  it('leaves tOr and plain calls alone', () => {
    expect(orAfterT("const a = tOr('app.x', 'fallback')\nconst b = t('app.y') + 'z'\nconst c = cond || t('app.z')")).toEqual([])
  })
})

describe('the dictionaries against the code', () => {
  const used = Object.entries(sources).map(([file, text]) => ({ file, text }))

  for (const [lang, dictionary] of Object.entries(dictionaries)) {
    it(`has every key of every namespace that the code asks for, in ${lang}`, () => {
      const missing = used.flatMap(({ file, text }) => anyNamespaceKeysIn(text).filter((key) => !(key in dictionary)).map((key) => `${file}: ${key}`))
      expect(missing).toEqual([])
    })

    it(`passes every placeholder that its ${lang} string has`, () => {
      const short = used.flatMap(({ file, text }) =>
        paramCalls(text).flatMap(({ key, names }) => {
          const lacking = placeholdersOf(dictionary[key] ?? '').filter((name) => !names.includes(name))
          return lacking.length === 0 ? [] : [`${file}: ${key} lacks {${lacking.join('}, {')}}`]
        }),
      )
      expect(short).toEqual([])
    })
  }

  it('has no t(…) followed by || or ??, where the fallback can never run', () => {
    const offenders = used.flatMap(({ file, text }) => orAfterT(text).map((line) => `${file}:${line}`))
    expect(offenders).toEqual([])
  })
})
