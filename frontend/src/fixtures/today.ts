import type { TodayView } from '@/features/today/types'
import { toIsoDate } from '@/lib/dates'
import { FIXTURE_NOW, FIXTURE_TODAY, latestWeight, nights } from './series'

const last = nights[nights.length - 1]

/** The Today screen as the mockup draws it, in the shape the API will send. */
export const todayFixture: TodayView = {
  dateIso: toIsoDate(FIXTURE_TODAY),
  now: FIXTURE_NOW,
  sync: [
    { source: 'Garmin', at: '2026-09-29T07:02:00', ok: true },
    { source: 'Hevy', at: '2026-09-27T19:40:00', ok: true },
  ],
  narrative: {
    // Prepositions are glued to the next word with U+00A0, as in the mockup.
    lead: 'Вес 86,1 и уходит на 0,6 в неделю.',
    note: 'Сон 82, но HRV третью ночь ниже нормы.',
  },
  weight: { kg: latestWeight, weekDeltaKg: -0.6, todayKg: latestWeight, measuredAt: '07:55' },
  sleep: { score: 82, minutes: 454 },
  hrv: { ms: last?.hrv ?? 46, lo: 50, hi: 58 },
  bodyBattery: { value: 94, gained: 58 },
  intake: { kcal: 420, target: 2100 },
  weekChanges: [
    { metric: 'weight', unit: 'кг', from: 87.0, to: 86.2, lo: 80, hi: 80, min: 84.5, max: 88.5, better: -1, screen: 'weight' },
    { metric: 'sleep', unit: '', from: 81.6, to: 84.2, lo: 72, hi: 88, min: 65, max: 95, better: 1, screen: 'recovery' },
    { metric: 'hrv', unit: 'мс', from: 53.8, to: 47.5, lo: 50, hi: 58, min: 40, max: 64, better: 1, screen: 'recovery' },
    { metric: 'bb', unit: '', from: 86.1, to: 90.8, lo: 70, hi: 92, min: 60, max: 100, better: 1, screen: 'recovery' },
  ],
  feed: [
    { time: '07:02', tone: 'cool', text: 'Garmin синхронизирован', detail: 'сон 82 · 7 ч 34 мин · HRV 46 мс' },
    { time: '07:40', tone: 'accent', text: 'Утренний бриф отправлен', detail: 'проактивный слой · Telegram' },
    { time: '07:55', tone: 'good', text: 'Вес 86,1 кг', detail: 'вручную' },
    { time: '08:05', tone: 'good', text: 'Завтрак · 420 ккал', detail: 'овсянка, яйца, кофе · белок 31 г' },
  ],
  attention: [
    {
      tone: 'note',
      lead: 'Наблюдение · ',
      parts: ['HRV третью ночь ниже твоего коридора 50–58 мс, пульс покоя на верхней границе. Восстановление отстаёт от нагрузки.'],
      evidence: 'Garmin · 14 ночей',
    },
    {
      tone: 'warn',
      parts: [{ strong: 'Витамин D 28 нг/мл' }, ' — ниже референса ', { nw: '30–100' }, '.'],
      evidence: 'анализ от 6 сентября · правило «добавки ↔ анализы»',
      screen: 'labs',
    },
    { tone: 'info', parts: ['Инъекция по графику — ', { strong: 'воскресенье, 4 октября' }, '.'] },
  ],
  goal: {
    startKg: 94.0,
    targetKg: 80,
    deadlineIso: '2026-12-27',
    forecast: 'При нынешнем тренде — около 10 декабря, на 17 дней раньше срока.',
  },
}
