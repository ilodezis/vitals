import { describe, expect, it } from 'vitest'

const tsxSources = import.meta.glob<string>(
  [
    '/src/**/*.tsx',
    '!/src/**/*.test.tsx',
    '!/src/fixtures/**',
  ],
  {
    query: '?raw',
    import: 'default',
    eager: true,
  },
)

const TAILWIND_TOKEN_RE = /\b(flex|items-[a-z]+|justify-[a-z]+|p[xytrbl]?-\d+|m[xytrbl]?-\d+|gap-\d+|text-(xs|sm|lg)|cursor-pointer|w-full|space-[xy]-\d+)\b/

export function findTailwindClasses(source: string): string[] {
  const matches: string[] = []
  // Matches className="..." or className='...' or string literals inside className={...} / cx(...)
  const classNameAttrRe = /className\s*=\s*(?:\{([^}]+)\}|"([^"]+)"|'([^']+)')/g
  let attrMatch: RegExpExecArray | null
  while ((attrMatch = classNameAttrRe.exec(source)) !== null) {
    const rawContent = attrMatch[1] ?? attrMatch[2] ?? attrMatch[3] ?? ''
    // Extract string literals or plain words
    const stringLiteralRe = /['"`]([^'"`]+)['"`]/g
    let strMatch: RegExpExecArray | null
    let foundInside = false
    while ((strMatch = stringLiteralRe.exec(rawContent)) !== null) {
      foundInside = true
      const matchedStr = strMatch[1] ?? ''
      const tokens = matchedStr.split(/\s+/)
      for (const token of tokens) {
        if (TAILWIND_TOKEN_RE.test(token)) {
          matches.push(token)
        }
      }
    }
    if (!foundInside) {
      const tokens = rawContent.split(/\s+/)
      for (const token of tokens) {
        if (TAILWIND_TOKEN_RE.test(token)) {
          matches.push(token)
        }
      }
    }
  }
  return matches
}

describe('noTailwind', () => {
  it('ensures zero Tailwind utility classes in any .tsx file', () => {
    const entries = Object.entries(tsxSources)
    expect(entries.length).toBeGreaterThan(20)

    const offenders: { file: string; tokens: string[] }[] = []
    for (const [file, content] of entries) {
      const tokens = findTailwindClasses(content)
      if (tokens.length > 0) {
        offenders.push({ file, tokens })
      }
    }

    expect(offenders).toEqual([])
  })
})
