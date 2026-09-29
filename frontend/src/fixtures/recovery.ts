import type { RecoveryView } from '@/features/recovery/types'
import { toIsoDate } from '@/lib/dates'
import { FIXTURE_TODAY, hypnogram, nights, stageMinutes } from './series'

const last = nights[nights.length - 1]

export const recoveryFixture: RecoveryView = {
  headline: {
    sleepScore: 82,
    sleepMinutes: 454,
    hrv: last?.hrv ?? 46,
    hrvNightsBelow: 3,
    rhr: last?.rhr ?? 52,
    rhrNote: 'верх нормы',
    bodyBatteryFrom: 36,
    bodyBatteryTo: 94,
  },
  night: {
    dateIso: toIsoDate(FIXTURE_TODAY),
    start: '23:40',
    end: '07:14',
    stages: hypnogram,
    stageMinutes,
  },
  norms: {
    sleep: { lo: 72, hi: 88, better: 1, unit: '' },
    hrv: { lo: 50, hi: 58, better: 1, unit: 'мс' },
    rhr: { lo: 48, hi: 53, better: -1, unit: 'уд/мин' },
    stress: { lo: 18, hi: 32, better: -1, unit: '' },
    steps: { lo: 7000, hi: 11000, better: 1, unit: '' },
    bb: { lo: 70, hi: 92, better: 1, unit: '' },
  },
  bars: [
    { key: 'sleep', min: 40, max: 100 },
    { key: 'hrv', min: 35, max: 70 },
    { key: 'rhr', min: 44, max: 60 },
    { key: 'stress', min: 0, max: 60 },
  ],
  days: nights.map((n) => ({
    dateIso: toIsoDate(n.date),
    sleep: n.sleep,
    hrv: n.hrv,
    rhr: n.rhr,
    stress: n.stress,
    steps: n.steps,
    bb: n.bb,
  })),
}
