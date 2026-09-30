import { describe, expect, it } from 'vitest'
import { buildProactiveNumbers, type ProactiveNumberFields } from './proactiveBody'

const filled: ProactiveNumberFields = {
  dailyBudget: '5',
  syncHours: '6',
  weightExportMinutes: '15',
  weightMaxAgeDays: '30',
  pulseSeconds: '600',
  pulseStartHour: '7',
  pulseEndHour: '23',
}

describe('buildProactiveNumbers', () => {
  it('reads every field as typed', () => {
    expect(buildProactiveNumbers(filled)).toEqual({
      ok: true,
      numbers: {
        daily_budget: 5,
        garmin_sync_hours: 6,
        garmin_weight_export_minutes: 15,
        garmin_weight_max_age_days: 30,
        pulse_seconds: 600,
        pulse_start_hour: 7,
        pulse_end_hour: 23,
      },
    })
  })

  it('keeps 0 pulse seconds: that is "off", not a blank to fill in', () => {
    const result = buildProactiveNumbers({ ...filled, pulseSeconds: '0' })
    expect(result.ok).toBe(true)
    if (result.ok) expect(result.numbers.pulse_seconds).toBe(0)
  })

  it('keeps 0 in any other field instead of swapping in a default', () => {
    const result = buildProactiveNumbers({ ...filled, dailyBudget: '0', pulseStartHour: '0' })
    expect(result.ok).toBe(true)
    if (result.ok) {
      expect(result.numbers.daily_budget).toBe(0)
      expect(result.numbers.pulse_start_hour).toBe(0)
    }
  })

  it('refuses an empty field and names it, so nothing is sent', () => {
    expect(buildProactiveNumbers({ ...filled, syncHours: '' })).toEqual({ ok: false, invalid: ['syncHours'] })
    expect(buildProactiveNumbers({ ...filled, syncHours: '   ' })).toEqual({ ok: false, invalid: ['syncHours'] })
  })

  it('refuses text, fractions and negatives', () => {
    const result = buildProactiveNumbers({ ...filled, dailyBudget: 'abc', pulseSeconds: '1.5', pulseEndHour: '-2' })
    expect(result).toEqual({ ok: false, invalid: ['dailyBudget', 'pulseSeconds', 'pulseEndHour'] })
  })
})
