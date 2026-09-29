import { describe, expect, it } from 'vitest'
import mockup from '../../../../docs/design/mockup/icons.js?raw'
import { ICONS } from './paths'

// The mockup is the visual truth: every icon it draws exists here, stroke for stroke.
function parseMockup(source: string): Record<string, string> {
  const icons: Record<string, string> = {}
  for (const [, name, svg] of source.matchAll(/^ {2}(\w+): '(.*)',$/gm)) {
    if (name !== undefined && svg !== undefined) icons[name] = svg
  }
  return icons
}

describe('icon family', () => {
  const fromMockup = parseMockup(mockup)

  it('reads the mockup dictionary', () => {
    expect(Object.keys(fromMockup).length).toBeGreaterThan(30)
  })

  it('matches the mockup exactly', () => {
    expect(ICONS).toEqual(fromMockup)
  })
})
