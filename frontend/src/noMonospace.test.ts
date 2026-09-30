import { describe, expect, it } from 'vitest'

const cssFiles = import.meta.glob<string>(
  [
    '/src/**/*.css',
  ],
  {
    query: '?raw',
    import: 'default',
    eager: true,
  },
)

const FORBIDDEN_PATTERNS = ['monospace', '--f-mono', 'JetBrains', 'Courier']

describe('noMonospace guard', () => {
  it('ensures no css file in src/ uses monospace, --f-mono, JetBrains, or Courier', () => {
    const paths = Object.keys(cssFiles)
    expect(paths.length).toBeGreaterThan(0)

    const violations: { file: string; line: number; text: string; pattern: string }[] = []

    for (const [filePath, content] of Object.entries(cssFiles)) {
      const lines = content.split('\n')
      lines.forEach((lineText: string, idx: number) => {
        for (const pattern of FORBIDDEN_PATTERNS) {
          if (lineText.toLowerCase().includes(pattern.toLowerCase())) {
            violations.push({
              file: filePath,
              line: idx + 1,
              text: lineText.trim(),
              pattern,
            })
          }
        }
      })
    }

    if (violations.length > 0) {
      const message = violations
        .map((v) => `  ${v.file}:${v.line} matched "${v.pattern}": ${v.text}`)
        .join('\n')
      expect.fail(`Found monospace font references in CSS:\n${message}`)
    }
  })
})
