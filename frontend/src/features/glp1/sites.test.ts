import { describe, expect, it } from 'vitest'
import { parseIsoDate } from '@/lib/dates'
import { glp1Fixture } from '@/fixtures/glp1'
import { siteUsage } from './sites'

const today = new Date(2026, 8, 29)

describe('injection site rotation', () => {
  const usage = siteUsage(glp1Fixture.injections, today, parseIsoDate)
  const by = (site: string) => usage.find((u) => u.site === site)

  it('suggests the site that was used least recently — a never-used one first', () => {
    expect(usage[0]?.site).toBe('shoulder_left')
    expect(usage[0]?.mark.kind).toBe('next')
    expect(usage[0]?.last).toBeNull()
  })

  it('marks the last few days as recent and dims older ones the longer ago they were', () => {
    expect(by('thigh_left')?.mark.kind).toBe('recent') // 27 Sep: two days ago
    const older = by('abdomen_right')?.mark // 20 Sep: nine days ago
    expect(older?.kind).toBe('older')
    expect(older?.kind === 'older' ? older.opacity : 0).toBeCloseTo(0.475, 3)
    const oldest = by('abdomen_left')?.mark // 6 Sep: 23 days ago, dimmer still
    expect(oldest?.kind === 'older' ? oldest.opacity : 1).toBeLessThan(0.2)
  })

  it('lists sites from least to most recently used', () => {
    const dates = usage.map((u) => u.last?.getTime() ?? 0)
    expect(dates).toEqual([...dates].sort((a, b) => a - b))
  })

  it('takes the most recent injection when a site was used more than once', () => {
    expect(by('thigh_left')?.last).toEqual(new Date(2026, 8, 27))
    expect(by('abdomen_right')?.last).toEqual(new Date(2026, 8, 20))
  })
})
