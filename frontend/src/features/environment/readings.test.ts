import { describe, expect, it } from 'vitest'
import { THRESHOLDS } from '@/fixtures/environment'
import { agoText, co2ZoneOf, humidityVerdict, minutesText, parseTs, stationAgeS, tempVerdict, trendOf } from './readings'

const t = (key: string, params?: Record<string, string | number>) => `${key}${params ? JSON.stringify(params) : ''}`

describe('parseTs', () => {
  it('reads a time with a zone as the instant it names', () => {
    expect(parseTs('2026-10-05T14:03:10Z')).toBe(Date.UTC(2026, 9, 5, 14, 3, 10))
    expect(parseTs('2026-10-05T17:03:10+03:00')).toBe(Date.UTC(2026, 9, 5, 14, 3, 10))
    expect(parseTs('2026-10-05T17:03:10+0300')).toBe(Date.UTC(2026, 9, 5, 14, 3, 10))
    expect(parseTs('2026-10-05T14:03:10.250000Z')).toBe(Date.UTC(2026, 9, 5, 14, 3, 10, 250))
  })

  it('reads a time without a zone as the wall clock, the way the rest of the app does', () => {
    expect(parseTs('2026-10-05T14:03:10')).toBe(new Date(2026, 9, 5, 14, 3, 10).getTime())
    expect(parseTs('2026-10-05 14:03')).toBe(new Date(2026, 9, 5, 14, 3, 0).getTime())
  })

  it('does not take the day of a date for a zone', () => {
    expect(parseTs('2026-10-05')).toBeNull()
    expect(parseTs('nonsense')).toBeNull()
  })
})

describe('co2ZoneOf', () => {
  it.each([
    [null, 'none'],
    [420, 'good'],
    [799, 'good'],
    [800, 'ok'],
    [999, 'ok'],
    [1000, 'warn'],
    [1399, 'warn'],
    [1400, 'bad'],
    [3000, 'bad'],
  ] as const)('puts %s ppm in %s', (ppm, zone) => {
    expect(co2ZoneOf(ppm, THRESHOLDS)).toBe(zone)
  })

  it('follows the owner’s thresholds, not fixed ones', () => {
    expect(co2ZoneOf(900, { co2_ok_max: 600, co2_warn: 850, co2_bad: 1200 })).toBe('warn')
  })
})

describe('trendOf', () => {
  it('calls a small drift steady and a real one by its direction', () => {
    expect(trendOf(null)).toBeNull()
    expect(trendOf(12)).toBe('flat')
    expect(trendOf(-29)).toBe('flat')
    expect(trendOf(120)).toBe('up')
    expect(trendOf(-400)).toBe('down')
  })
})

describe('verdicts', () => {
  it('judges the temperature against the day range and the humidity against the comfort range', () => {
    expect(tempVerdict(null, THRESHOLDS)).toBeNull()
    expect(tempVerdict(16.5, THRESHOLDS)).toBe('cold')
    expect(tempVerdict(21, THRESHOLDS)).toBe('ok')
    expect(tempVerdict(27, THRESHOLDS)).toBe('hot')
    expect(humidityVerdict(28, THRESHOLDS)).toBe('dry')
    expect(humidityVerdict(45, THRESHOLDS)).toBe('ok')
    expect(humidityVerdict(66, THRESHOLDS)).toBe('humid')
  })
})

describe('how long ago', () => {
  const station = { status: 'online', last_seen_at: null, age_s: 4, rssi: null, fw: null } as const

  it('adds the time the answer has been here to the age the server gave', () => {
    expect(stationAgeS(station, 1_000_000, 1_007_000)).toBe(11)
  })

  it('has no age when the server gave none', () => {
    expect(stationAgeS({ ...station, age_s: null }, 0, 1000)).toBeNull()
  })

  it('never runs backwards if the clock does', () => {
    expect(stationAgeS(station, 5000, 1000)).toBe(0)
  })

  it('names the unit that matters', () => {
    expect(agoText(4.4, t)).toBe('app.env.ago.s{"n":4}')
    expect(agoText(420, t)).toBe('app.duration.min{"m":7}')
    expect(agoText(3900, t)).toBe('app.duration.hm{"h":1,"m":5}')
    expect(minutesText(190, t)).toBe('app.duration.hm{"h":3,"m":10}')
    expect(minutesText(40, t)).toBe('app.duration.min{"m":40}')
  })
})
