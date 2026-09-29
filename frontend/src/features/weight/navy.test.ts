import { describe, expect, it } from 'vitest'
import { computeNavyFatPct } from './navy'

describe('computeNavyFatPct', () => {
  it('calculates male body fat percentage correctly', () => {
    // Height: 190 cm, Waist: 85 cm, Neck: 38 cm
    const fat = computeNavyFatPct(85, 38, 190, 'male')
    expect(fat).not.toBeNull()
    expect(fat).toBeGreaterThan(10)
    expect(fat).toBeLessThan(25)
  })

  it('returns null on invalid / non-positive geometry', () => {
    expect(computeNavyFatPct(38, 38, 190, 'male')).toBeNull() // waist <= neck
    expect(computeNavyFatPct(35, 38, 190, 'male')).toBeNull()
    expect(computeNavyFatPct(85, 38, 0, 'male')).toBeNull()
  })

  it('calculates female body fat percentage when hips are provided', () => {
    const fat = computeNavyFatPct(70, 32, 168, 'female', 95)
    expect(fat).not.toBeNull()
    expect(fat).toBeGreaterThan(15)
  })

  it('returns null for female without hips', () => {
    expect(computeNavyFatPct(70, 32, 168, 'female')).toBeNull()
  })
})
