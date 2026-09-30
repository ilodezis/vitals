import { describe, expect, it } from 'vitest'

/* The rules of the design system that used to be checked against the server-rendered
   stylesheet, kept here against the stylesheets the app ships: a type ladder nothing
   falls off, radii from the token set, no `transition: all`, touch targets a thumb can hit. */

const sheets = import.meta.glob('../**/*.css', { query: '?raw', import: 'default', eager: true }) as Record<string, string>
const named = Object.entries(sheets).map(([path, css]) => ({ path: path.replace(/^\.\.\//, '').replace(/^\.\//, 'styles/'), css: css.replace(/\/\*[\s\S]*?\*\//g, '') }))

function declarations(property: string): { path: string; value: string }[] {
  const found: { path: string; value: string }[] = []
  const re = new RegExp(`(?:^|[\\s;{])${property}\\s*:\\s*([^;}\\n]+)`, 'g')
  for (const { path, css } of named) {
    for (const match of css.matchAll(re)) found.push({ path, value: (match[1] ?? '').trim() })
  }
  return found
}

/** The type ladder of tokens.css, in px. */
const LADDER = new Set([11, 12, 13, 14, 15, 18, 22, 28, 38])
/** Display figures (the big numerals) sit above the ladder on purpose. */
const DISPLAY_FROM = 38
/** Sizes between rungs that were set by hand, each with the file that owns it. A new one needs a
 *  reason to be here; none of them may be added to get a screen to look right. */
const OFF_LADDER = new Set(['styles/app.css 16px', 'styles/app.css 34px', 'features/hrt/hrt.css 24px', 'features/today/today.css 29px'])

describe('the type ladder', () => {
  it('has stylesheets to check', () => {
    expect(named.length).toBeGreaterThan(10)
  })

  it('has no text smaller than 11px', () => {
    const tooSmall = declarations('font-size').filter(({ value }) => {
      const px = /^(\d+(?:\.\d+)?)px$/.exec(value)
      return px !== null && Number(px[1]) < 11
    })
    expect(tooSmall).toEqual([])
  })

  it('sets text on a rung of the ladder or as a display figure', () => {
    const stray = declarations('font-size')
      .filter(({ value }) => {
        if (value.startsWith('var(--t-') || value === 'inherit' || value === '1em' || value === '100%') return false
        const px = /^(\d+(?:\.\d+)?)px$/.exec(value)
        if (px === null) return true
        const size = Number(px[1])
        return !(LADDER.has(size) || size >= DISPLAY_FROM)
      })
      .filter(({ path, value }) => !OFF_LADDER.has(`${path} ${value}`))
    expect(stray).toEqual([])
  })
})

describe('shape and motion', () => {
  it('rounds corners from the radius tokens, or with the few shapes that are not corners', () => {
    // Not corners: a hairline bar's 1-4px, a circle, a pill, and the bottom sheet's top edge.
    const shapes = new Set(['0', '50%', '999px', 'inherit', '1px', '2px', '3px', '4px', '28px'])
    const stray = declarations('border-radius').filter(({ value }) => {
      const rest = value.replace(/var\(--r[\w-]*(?:,[^)]*)?\)/g, ' ').trim()
      return rest !== '' && !rest.split(/\s+/).every((part) => shapes.has(part))
    })
    expect(stray).toEqual([])
  })

  it('never transitions "all": a change names what it animates', () => {
    const all = declarations('transition').filter(({ value }) => /^all\b/.test(value))
    expect(all).toEqual([])
  })
})

describe('touch targets', () => {
  it('makes the icon button at least 44px square', () => {
    const app = named.find(({ path }) => path === 'styles/app.css')
    const rule = /(?:^|\n)\.ibtn\s*\{([^}]*)\}/.exec(app?.css ?? '')?.[1] ?? ''
    const width = /width:\s*(\d+)px/.exec(rule)?.[1]
    const height = /height:\s*(\d+)px/.exec(rule)?.[1]
    expect(Number(width)).toBeGreaterThanOrEqual(44)
    expect(Number(height)).toBeGreaterThanOrEqual(44)
  })
})
