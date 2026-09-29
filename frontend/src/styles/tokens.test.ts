import { describe, expect, it } from 'vitest'
import mockupCss from '../../../docs/design/mockup/src/styles.css?raw'
import tokensCss from './tokens.css?raw'

function rootTokens(css: string): Map<string, string> {
  const root = /:root\s*\{([\s\S]*?)\n\}/.exec(css)?.[1] ?? ''
  const withoutComments = root.replace(/\/\*[\s\S]*?\*\//g, '')
  const tokens = new Map<string, string>()
  for (const [, name, value] of withoutComments.matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g)) {
    if (name !== undefined && value !== undefined) tokens.set(name, value.trim())
  }
  return tokens
}

const FONT_TOKENS = new Set(['--f-display', '--f-text'])

describe('design tokens', () => {
  const mockup = rootTokens(mockupCss)
  const app = rootTokens(tokensCss)

  it('carries every mockup token with the same value', () => {
    expect(mockup.size).toBeGreaterThan(50)
    for (const [name, value] of mockup) {
      if (FONT_TOKENS.has(name)) continue
      expect(app.get(name), name).toBe(value)
    }
    expect([...app.keys()].sort()).toEqual([...mockup.keys()].sort())
  })

  it('never lets the display face fall straight to a generic family', () => {
    const families = (app.get('--f-display') ?? '').split(',').map((f) => f.trim())
    expect(families.slice(0, 2)).toEqual(["'Geologica Variable'", "'Golos Text Variable'"])
  })

  it('sets text in Golos Text first', () => {
    expect(app.get('--f-text')?.startsWith("'Golos Text Variable'")).toBe(true)
  })
})
