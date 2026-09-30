import { describe, expect, it } from 'vitest'

const sourceFiles = import.meta.glob<string>(
  [
    '/src/features/**/*.{ts,tsx}',
    '/src/components/**/*.{ts,tsx}',
    '!/src/**/*.test.{ts,tsx}',
    '!/src/**/__tests__/**',
    '!/src/fixtures/**',
  ],
  {
    query: '?raw',
    import: 'default',
    eager: true,
  },
)

const CYRILLIC_RE = /[\u0400-\u04FF]/

/** Strip block and line comments to avoid false positives on docstrings / comments. */
function stripComments(code: string): string {
  // Replace multi-line comments
  let clean = code.replace(/\/\*[\s\S]*?\*\//g, (m) => ' '.repeat(m.length))
  // Replace single-line comments
  clean = clean.replace(/\/\/.*$/gm, (m) => ' '.repeat(m.length))
  return clean
}

export function findCyrillicViolations(filePath: string, source: string) {
  const codeWithoutComments = stripComments(source)
  const lines = codeWithoutComments.split('\n')
  const violations: { file: string; line: number; text: string }[] = []

  lines.forEach((line, idx) => {
    if (CYRILLIC_RE.test(line)) {
      violations.push({
        file: filePath,
        line: idx + 1,
        text: line.trim(),
      })
    }
  })

  return violations
}

describe('noHardcodedCopy guard', () => {
  it('ensures zero hardcoded Cyrillic string literals or JSX text in src/features and src/components', () => {
    const entries = Object.entries(sourceFiles)
    expect(entries.length).toBeGreaterThan(20)

    const allViolations: { file: string; line: number; text: string }[] = []
    for (const [filePath, content] of entries) {
      const violations = findCyrillicViolations(filePath, content)
      if (violations.length > 0) {
        allViolations.push(...violations)
      }
    }

    if (allViolations.length > 0) {
      const message = allViolations
        .map((v) => `  ${v.file}:${v.line} -> ${v.text}`)
        .join('\n')
      expect.fail(`Found hardcoded Cyrillic text in UI code:\n${message}`)
    }

    expect(allViolations).toEqual([])
  })
})
