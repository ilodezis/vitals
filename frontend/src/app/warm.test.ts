import { describe, expect, it } from 'vitest'
import { runWarm } from './warm'

describe('runWarm', () => {
  it('runs every job, never more than `parallel` at once, and skips a failing one', async () => {
    let inFlight = 0
    let peak = 0
    const ran: number[] = []
    const job = (n: number) => async () => {
      inFlight += 1
      peak = Math.max(peak, inFlight)
      await Promise.resolve()
      inFlight -= 1
      ran.push(n)
      if (n === 2) throw new Error('read failed')
    }
    await runWarm([0, 1, 2, 3, 4, 5].map(job), 2)
    expect(ran.sort()).toEqual([0, 1, 2, 3, 4, 5])
    expect(peak).toBeLessThanOrEqual(2)
  })
})
