import { describe, expect, it } from 'vitest'

const featureCss = import.meta.glob<string>('/src/features/**/*.css', {
  query: '?raw',
  import: 'default',
  eager: true,
})

// The in-place form's own classes, used by many screens.
const SHARED = /(^|[\s,])\.(fpanel|form-acts|form-g2)(\s+\.form)?\s*[{,]/

describe('sharedFormStyles guard', () => {
  it('keeps the in-place form\'s layout out of screen stylesheets, which load only with their screen', () => {
    const paths = Object.keys(featureCss)
    expect(paths.length).toBeGreaterThan(0)

    const violations: string[] = []
    for (const [filePath, content] of Object.entries(featureCss)) {
      content.split('\n').forEach((lineText, idx) => {
        if (SHARED.test(lineText)) violations.push(`  ${filePath}:${idx + 1}: ${lineText.trim()}`)
      })
    }

    if (violations.length > 0) expect.fail(`Shared form layout defined in a screen's stylesheet:\n${violations.join('\n')}`)
  })
})
