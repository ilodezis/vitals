import { describe, expect, it } from 'vitest'
import { clampStep, repeatDelay, WEIGHT_MAX, WEIGHT_MIN } from './stepperMath'

describe('stepper arithmetic', () => {
  it('moves in tenths without floating-point drift', () => {
    let v = 86.1
    for (let i = 0; i < 7; i++) v = clampStep(v + 0.1)
    expect(v).toBe(86.8)
    for (let i = 0; i < 10; i++) v = clampStep(v - 0.1)
    expect(v).toBe(85.8)
  })

  it('keeps a typed value inside 30–250', () => {
    expect(clampStep(12)).toBe(WEIGHT_MIN)
    expect(clampStep(400)).toBe(WEIGHT_MAX)
    expect(clampStep(86.14)).toBe(86.1)
    expect(clampStep(86.16)).toBe(86.2)
  })

  it('repeats faster the longer a key is held', () => {
    expect(repeatDelay(0)).toBe(110)
    expect(repeatDelay(5)).toBe(110)
    expect(repeatDelay(6)).toBe(60)
    expect(repeatDelay(15)).toBe(60)
    expect(repeatDelay(16)).toBe(30)
    expect(repeatDelay(200)).toBe(30)
  })
})
