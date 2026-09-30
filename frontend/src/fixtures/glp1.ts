import type { Glp1View } from '@/features/glp1/types'
import { toIsoDate } from '@/lib/dates'
import { FIXTURE_TODAY, weightTrend } from './series'

export const glp1Fixture: Glp1View = {
  drug: 'Семаглутид',
  doseMg: 0.5,
  sinceIso: '2026-08-02',
  dayOnDose: 58,
  deltaOnDoseKg: -3.1,
  cycle: { lastIso: '2026-09-27', nextIso: '2026-10-04', daysToNext: 5, overdue: false, unscheduled: false },
  dosePhases: [
    { fromIso: '2026-07-05', toIso: '2026-08-01', doseMg: 0.25 },
    { fromIso: '2026-08-02', toIso: toIsoDate(FIXTURE_TODAY), doseMg: 0.5 },
  ],
  trend: weightTrend
    .filter((p) => p.date >= new Date(2026, 5, 29))
    .map((p) => ({ date: toIsoDate(p.date), kg: p.value })),
  siteLabels: {
    shoulder_left: 'Плечо Л',
    shoulder_right: 'Плечо П',
    abdomen_left: 'Живот Л',
    abdomen_right: 'Живот П',
    thigh_left: 'Бедро Л',
    thigh_right: 'Бедро П',
  },
  injections: [
    { dateIso: '2026-09-27', site: 'thigh_left', doseMg: 0.5 },
    { dateIso: '2026-09-20', site: 'abdomen_right', doseMg: 0.5 },
    { dateIso: '2026-09-13', site: 'thigh_right', doseMg: 0.5 },
    { dateIso: '2026-09-06', site: 'abdomen_left', doseMg: 0.5 },
    { dateIso: '2026-08-30', site: 'thigh_left', doseMg: 0.5 },
    { dateIso: '2026-08-23', site: 'abdomen_right', doseMg: 0.5 },
    { dateIso: '2026-08-16', site: 'shoulder_right', doseMg: 0.5 },
    { dateIso: '2026-08-09', site: 'abdomen_left', doseMg: 0.5 },
  ],
  sideEffects: [
    { dateIso: '2026-08-13', name: 'Запор', severity: 3 },
    { dateIso: '2026-08-06', name: 'Тошнота', severity: 2 },
    { dateIso: '2026-07-23', name: 'Изжога', severity: 1 },
  ],
}
