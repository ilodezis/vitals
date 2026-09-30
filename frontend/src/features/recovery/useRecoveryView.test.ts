import { describe, expect, it } from 'vitest'
import type { components } from '@/api/schema'
import { toRecoveryView } from './useRecoveryView'

type RawRecoveryView = components['schemas']['RecoveryView']

/** A watch that has reported nothing. */
const SILENT: RawRecoveryView = {
  bars: [],
  date: '2026-09-30',
  days: [],
  headline: { hrv_nights_below: 0, rhr_note: '' },
  is_configured: false,
  is_today: true,
  norms: {},
  norms_days: 0,
  norms_min_days: 14,
  today_date: '2026-09-30',
}

describe('toRecoveryView', () => {
  it('keeps what the watch did not report as null, never as a zero or a typical night', () => {
    const view = toRecoveryView(SILENT)

    expect(view.headline).toEqual({
      sleepScore: null,
      sleepMinutes: null,
      hrv: null,
      hrvNightsBelow: 0,
      rhr: null,
      rhrNote: '',
      bodyBatteryFrom: null,
      bodyBatteryTo: null,
    })
    expect(view.night).toBeNull()
    expect(view.norms).toEqual({})
    expect(view.days).toEqual([])
  })

  it('has no bedtime for a night that recorded none', () => {
    const view = toRecoveryView({ ...SILENT, night: { date: '2026-09-30', start: '', end: '', stages: [], stage_minutes: [] } })

    expect(view.night).toEqual({ dateIso: '2026-09-30', start: null, end: null, stages: [], stageMinutes: null })
  })

  it('carries the codes of the resting pulse note and of the units for the screen to word', () => {
    const view = toRecoveryView({
      ...SILENT,
      headline: { hrv_nights_below: 2, rhr: 55, rhr_note: 'upper' },
      norms: { hrv: { lo: 48, hi: 62, better: 1, unit: 'ms' }, rhr: { lo: 49, hi: 55, better: -1, unit: 'bpm' } },
    })

    expect(view.headline.rhrNote).toBe('upper')
    expect(view.norms.hrv?.unit).toBe('ms')
    expect(view.norms.rhr).toEqual({ lo: 49, hi: 55, better: -1, unit: 'bpm' })
  })

  it('keeps a bar without a corridor as a bare value, and says how much history the corridors rest on', () => {
    const bare = toRecoveryView({ ...SILENT, bars: [{ key: 'hrv', min: 35, max: 75, value: 52, unit: 'ms', tone: '' }] })

    expect(bare.normsDays).toBe(0)
    expect(bare.bars).toEqual([{ key: 'hrv', min: 35, max: 75, value: 52, unit: 'ms' }])

    const known = toRecoveryView({ ...SILENT, norms_days: 41, norms_min_days: 14 })

    expect(known.normsDays).toBe(41)
    expect(known.normsMinDays).toBe(14)
  })

  it('leaves a day’s missing readings null', () => {
    const view = toRecoveryView({ ...SILENT, days: [{ date: '2026-09-29', sleep: 81, hrv: 40.4 }] })

    expect(view.days).toEqual([{ dateIso: '2026-09-29', sleep: 81, hrv: 40.4, rhr: null, stress: null, steps: null, bb: null }])
  })
})
