import type { WeightView } from '@/features/weight/types'
import { addDays, toIsoDate } from '@/lib/dates'
import { FIXTURE_TODAY, latestWeight, weighings, weightTrend } from './series'

const iso = (back: number): string => toIsoDate(addDays(FIXTURE_TODAY, -back))

export const weightFixture: WeightView = {
  kg: latestWeight,
  average7: 86.2,
  weekDeltaKg: -0.8,
  bodyFatPct: 17.8,
  drug: 'семаглутид',
  weighings: weighings.map((p) => ({ date: toIsoDate(p.date), kg: p.value })),
  trend: weightTrend.map((p) => ({ date: toIsoDate(p.date), kg: p.value })),
  dosePhases: [
    { from: '2026-07-05', to: '2026-08-01', label: '0,25 мг' },
    { from: '2026-08-02', to: toIsoDate(FIXTURE_TODAY), label: '0,5 мг' },
  ],
  history: [
    { date: iso(0), time: '07:55', kg: 86.1, source: 'manual' },
    { date: iso(1), time: '08:02', kg: 86.4, source: 'manual' },
    { date: iso(1), time: '07:40', kg: 86.9, source: 'garmin', superseded: true },
    { date: iso(3), time: '08:10', kg: 86.3, source: 'manual' },
    { date: iso(4), time: '07:48', kg: 86.8, source: 'garmin' },
    { date: iso(6), time: '08:21', kg: 86.9, source: 'manual' },
    { date: iso(8), time: '09:05', kg: 87.2, source: 'manual' },
    { date: iso(17), time: '10:30', kg: 88.0, source: 'bia', note: 'InBody · жир 18,4 %' },
    { date: iso(17), time: '07:50', kg: 88.3, source: 'garmin', superseded: true },
    { date: iso(19), time: '08:00', kg: 88.2, source: 'manual' },
  ],
  pace: {
    perWeekKg: -0.6,
    dose: { label: '0,5 мг', sinceIso: '2026-08-02', days: 58, deltaKg: -3.1 },
    goal: { targetKg: 80, weeks: 10 },
  },
  lastScan: {
    device: 'InBody',
    dateIso: '2026-09-12',
    rows: [
      { label: 'Жир', value: '18,4', unit: '%' },
      { label: 'Скелетные мышцы', value: '39,2', unit: 'кг' },
      { label: 'Висцеральный жир', value: '7', unit: 'ур.' },
      { label: 'Вода', value: '53,1', unit: 'л' },
    ],
  },
}
