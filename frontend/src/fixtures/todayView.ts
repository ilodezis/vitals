import type { TodayView } from '@/features/today/types'

/** A day as `GET /api/v1/today` sends it — for the tests that need a view to patch. */
export function sampleTodayView(overrides: Partial<TodayView> = {}): TodayView {
  return {
    date: '2026-09-29',
    narrative: 'Вес 86,1 и уходит на 0,6 в неделю. Сон 82.',
    narrative_source: 'computed',
    sync: [{ source: 'Garmin', date: '2026-09-29' }],
    figures: [
      { key: 'weight', value: 86.1, trend: -0.6, baseline: null, corridor: null, sleep_seconds: null, gained: null },
      { key: 'sleep_score', value: 82, trend: null, baseline: 80, corridor: { lo: 72, hi: 88 }, sleep_seconds: 27240, gained: null },
      { key: 'hrv_avg', value: 46, trend: null, baseline: 54, corridor: { lo: 50, hi: 58 }, sleep_seconds: null, gained: null },
      { key: 'body_battery_high', value: 94, trend: null, baseline: 88, corridor: { lo: 70, hi: 92 }, sleep_seconds: null, gained: 58 },
      { key: 'calories', value: 420, trend: null, baseline: null, corridor: { lo: 1800, hi: 2200 }, sleep_seconds: null, gained: null },
    ],
    changes: [
      { key: 'weight', domain_key: 'weight', before: 87.0, after: 86.2, lo: null, hi: null, tone: 'good' },
      { key: 'hrv_avg', domain_key: 'garmin', before: 53.8, after: 47.5, lo: 50, hi: 58, tone: 'bad' },
    ],
    feed: [
      { time: '08:05', kind: 'meal', dot: 'good', text: 'Овсянка', detail: '', value: 420 },
      { time: '', kind: 'brief', dot: 'amber', text: '', detail: '', value: null },
    ],
    attention: [{ severity: 'warn', message: 'Витамин D ниже референса', domain: 'labs' }],
    goal: {
      name: 'Дойти до 80',
      start_kg: 94.0,
      current_kg: 86.1,
      target_kg: 80,
      deadline: '2026-12-27',
      forecast: { date: '2026-12-10', days_ahead: 17 },
    },
    latest_weight: { kg: 86.1, date: '2026-09-29' },
    ...overrides,
  }
}
