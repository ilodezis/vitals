/** The numeric fields of the proactive form, as typed. Nothing here has a stand-in value:
 *  an empty or unreadable field is reported, never replaced by a number the person did not enter. */
export interface ProactiveNumberFields {
  dailyBudget: string
  syncHours: string
  weightExportMinutes: string
  weightMaxAgeDays: string
  pulseSeconds: string
  pulseStartHour: string
  pulseEndHour: string
}

export type ProactiveNumberKey = keyof ProactiveNumberFields

export interface ProactiveNumbers {
  daily_budget: number
  garmin_sync_hours: number
  garmin_weight_export_minutes: number
  garmin_weight_max_age_days: number
  pulse_seconds: number
  pulse_start_hour: number
  pulse_end_hour: number
}

const FIELD_TO_BODY: Record<ProactiveNumberKey, keyof ProactiveNumbers> = {
  dailyBudget: 'daily_budget',
  syncHours: 'garmin_sync_hours',
  weightExportMinutes: 'garmin_weight_export_minutes',
  weightMaxAgeDays: 'garmin_weight_max_age_days',
  pulseSeconds: 'pulse_seconds',
  pulseStartHour: 'pulse_start_hour',
  pulseEndHour: 'pulse_end_hour',
}

export type ProactiveNumbersResult =
  | { ok: true; numbers: ProactiveNumbers }
  | { ok: false; invalid: ProactiveNumberKey[] }

/** A whole number, zero included (`pulse_seconds` = 0 is the legitimate "off"). Ranges are the
 *  server's to enforce; this only refuses what is not a number at all. */
function readWhole(raw: string): number | null {
  const text = raw.trim()
  return /^\d+$/.test(text) ? Number(text) : null
}

export function buildProactiveNumbers(fields: ProactiveNumberFields): ProactiveNumbersResult {
  const read = readProactiveNumbers(fields)
  return read.ok ? { ok: true, numbers: read.numbers as ProactiveNumbers } : read
}

export type PartialNumbersResult =
  | { ok: true; numbers: Partial<ProactiveNumbers> }
  | { ok: false; invalid: ProactiveNumberKey[] }

/** The same reading for a part of the form: the Garmin schedule and the bot's own fields are
 *  saved by different blocks, and each sends only the numbers it shows. */
export function readProactiveNumbers(fields: Partial<ProactiveNumberFields>): PartialNumbersResult {
  const invalid: ProactiveNumberKey[] = []
  const numbers: Partial<ProactiveNumbers> = {}
  for (const key of Object.keys(FIELD_TO_BODY) as ProactiveNumberKey[]) {
    const raw = fields[key]
    if (raw === undefined) continue
    const value = readWhole(raw)
    if (value === null) invalid.push(key)
    else numbers[FIELD_TO_BODY[key]] = value
  }
  return invalid.length > 0 ? { ok: false, invalid } : { ok: true, numbers }
}
