import { describe, expect, it } from 'vitest'
import { switchDate } from './since'

describe('supplement start/stop date', () => {
  it('names the day and month in this year', () => {
    expect(switchDate('2026-09-03', '2026-10-12', 'ru')).toBe('3 сентября')
    expect(switchDate('2026-09-03', '2026-10-12', 'en')).toBe('September 3')
  })

  it('adds the year when it is another one', () => {
    expect(switchDate('2025-12-30', '2026-10-12', 'en')).toBe('December 30 2025')
  })
})
