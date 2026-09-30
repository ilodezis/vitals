import { describe, expect, it } from 'vitest'

const screens = import.meta.glob<string>(['/src/**/*.tsx', '!/src/**/*.test.tsx'], {
  query: '?raw',
  import: 'default',
  eager: true,
})

describe('noBrowserControls guard', () => {
  it('ensures a toggle or a 1–5 scale is one of the app\'s own controls, never the browser\'s checkbox or slider', () => {
    const paths = Object.keys(screens)
    expect(paths.length).toBeGreaterThan(0)

    const violations: string[] = []
    for (const [filePath, content] of Object.entries(screens)) {
      content.split('\n').forEach((lineText, idx) => {
        if (/type=["'](checkbox|range)["']/.test(lineText)) violations.push(`  ${filePath}:${idx + 1}: ${lineText.trim()}`)
      })
    }

    if (violations.length > 0) expect.fail(`Found browser-drawn controls:\n${violations.join('\n')}`)
  })
})
