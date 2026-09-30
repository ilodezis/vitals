import { describe, expect, it } from 'vitest'
import { SERIES_COLORS, seriesColor } from './seriesColors'

describe('series palette', () => {
  it('never uses amber or a raw hex colour', () => {
    for (const color of SERIES_COLORS) {
      expect(color).toMatch(/^var\(--[a-z0-9-]+\)$/)
      expect(color).not.toMatch(/--(accent|warn)/)
    }
  })

  it('gives every slot of the palette its own colour', () => {
    expect(new Set(SERIES_COLORS).size).toBe(SERIES_COLORS.length)
  })

  it('wraps slots past the end of the palette and tolerates negative ones', () => {
    expect(seriesColor(0)).toBe(SERIES_COLORS[0])
    expect(seriesColor(SERIES_COLORS.length)).toBe(SERIES_COLORS[0])
    expect(seriesColor(-1)).toBe(SERIES_COLORS[SERIES_COLORS.length - 1])
  })
})
