import { describe, expect, it } from 'vitest'
import { changeTone, percentOf, rangeBarLayout } from './gauges'

describe('gauges', () => {
  it('places a value on its scale and clamps at the ends', () => {
    expect(percentOf(50, 0, 100)).toBe(50)
    expect(percentOf(-5, 0, 100)).toBe(0)
    expect(percentOf(140, 0, 100)).toBe(100)
    expect(percentOf(86.2, 84.5, 88.5)).toBeCloseTo(42.5, 5)
  })

  it('draws the corridor as a band, and a target line when the corridor is one number', () => {
    const band = rangeBarLayout({ value: 47.5, lo: 50, hi: 58, min: 40, max: 64 })
    expect(band.ref?.left).toBeCloseTo(41.67, 1)
    expect(band.ref?.width).toBeCloseTo(33.33, 1)
    expect(rangeBarLayout({ value: 86.2, lo: 80, hi: 80, min: 84.5, max: 88.5 }).ref).toBeNull()
  })

  it('stretches from last week to this week whichever way it moved', () => {
    const down = rangeBarLayout({ value: 86.2, prev: 87, lo: 80, hi: 80, min: 84.5, max: 88.5 })
    expect(down.move?.from).toBeCloseTo(62.5, 5)
    expect(down.move?.left).toBeCloseTo(42.5, 5)
    expect(down.move?.width).toBeCloseTo(20, 5)
    expect(rangeBarLayout({ value: 5, lo: 1, hi: 9, min: 0, max: 10 }).move).toBeNull()
  })

  it('calls a change good when it goes the way that is better', () => {
    expect(changeTone(87, 86.2, -1)).toBe('good') // weight down
    expect(changeTone(53.8, 47.5, 1)).toBe('bad') // HRV down
    expect(changeTone(81.6, 84.2, 1)).toBe('good') // sleep up
    expect(changeTone(5, 5, 1)).toBe('')
  })
})
