import { describe, expect, it } from 'vitest'
import { changeTone, percentOf, rangeAxis, rangeBarLayout } from './gauges'

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

  it('draws no band for a metric that has no corridor', () => {
    expect(rangeBarLayout({ value: 5, lo: null, hi: null, min: 0, max: 10 }).ref).toBeNull()
    expect(rangeBarLayout({ value: 5, min: 0, max: 10 }).ref).toBeNull()
  })
})

describe('rangeAxis', () => {
  it('gives a weight with no corridor room by its own magnitude', () => {
    const axis = rangeAxis([87.0, 86.2])
    expect(axis.min).toBeCloseTo(84.47, 2)
    expect(axis.max).toBeCloseTo(88.73, 2)
  })

  it('leaves the corridor a margin on both sides', () => {
    const axis = rangeAxis([81.6, 84.2], { lo: 72, hi: 88 })
    expect(axis.min).toBeCloseTo(65.6, 5)
    expect(axis.max).toBeCloseTo(94.4, 5)
  })

  it('stretches to hold a value that left its corridor', () => {
    const axis = rangeAxis([53.8, 47.5], { lo: 50, hi: 58 })
    expect(axis.min).toBeCloseTo(43.3, 5)
    expect(axis.max).toBeCloseTo(62.2, 5)
  })

  it('never collapses to a point', () => {
    expect(rangeAxis([50, 50])).toEqual({ min: 49, max: 51 })
  })
})
