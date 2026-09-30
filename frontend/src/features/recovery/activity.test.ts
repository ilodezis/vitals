import { describe, expect, it } from 'vitest'
import type { components } from '@/api/schema'
import { hasDetail, lapTime } from './activity'

type ActivityItem = components['schemas']['ActivityItem']

const bare: ActivityItem = {
  id: '1',
  name: 'Walk',
  activity_type: 'walking',
  start_time: '2026-09-29T08:00:00',
  duration_seconds: 1800,
  hr_zones: [],
  splits: [],
}

describe('activity detail', () => {
  it('opens only when there is more than the summary', () => {
    expect(hasDetail(bare)).toBe(false)
    expect(hasDetail({ ...bare, splits: [{ index: 1 }] })).toBe(false)
    expect(hasDetail({ ...bare, avg_power: 210 })).toBe(true)
    expect(hasDetail({ ...bare, hr_zones: [{ zone: 2, seconds: 600 }] })).toBe(true)
    expect(hasDetail({ ...bare, splits: [{ index: 1 }, { index: 2 }] })).toBe(true)
  })

  it('prints a lap as minutes and seconds', () => {
    expect(lapTime(305)).toBe('5:05')
    expect(lapTime(59.6)).toBe('1:00')
  })
})
