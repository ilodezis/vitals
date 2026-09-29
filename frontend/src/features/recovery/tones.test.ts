import { describe, expect, it } from 'vitest'
import { deviation, isWorse, toneCell } from './tones'
import type { Norm } from './types'

const hrv: Norm = { lo: 50, hi: 58, better: 1, unit: 'мс' }
const rhr: Norm = { lo: 48, hi: 53, better: -1, unit: 'уд/мин' }

describe('recovery tones', () => {
  it('leaves a value inside the corridor uncoloured', () => {
    expect(toneCell(54, hrv)).toBe('')
    expect(deviation(50, hrv)).toBe(0)
    expect(deviation(58, hrv)).toBe(0)
  })

  it('reads below the corridor as worse when higher is better, and better when lower is', () => {
    expect(toneCell(46, hrv)).toBe('b2') // 4 below an 8-wide corridor: half a corridor
    expect(toneCell(46, rhr)).toBe('g2') // 2 below a 5-wide corridor where lower is better: 0.4 the good way
  })

  it('splits "a little" from "a lot" at a quarter of the corridor', () => {
    expect(toneCell(49, hrv)).toBe('b1') // 1/8 out
    expect(toneCell(47, hrv)).toBe('b2') // 3/8 out
    expect(toneCell(60, hrv)).toBe('g1') // 2/8 above, higher is better
    expect(toneCell(61, hrv)).toBe('g2')
  })

  it('prints only the worse side in the alarm colour', () => {
    expect(isWorse(46, hrv)).toBe(true)
    expect(isWorse(62, hrv)).toBe(false)
    expect(isWorse(56, rhr)).toBe(true)
    expect(isWorse(45, rhr)).toBe(false)
  })
})
