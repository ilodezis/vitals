/** The right-hand status of each row on More: a short phrase, and `bad` when it needs a look.
 *  Keyed by module key, as the session names them. */
export interface MoreStatus {
  text: string
  tone?: 'bad'
}

export const moreStatusFixture: Record<string, MoreStatus> = {
  weight: { text: '86,1 кг' },
  garmin: { text: 'сон 82' },
  hevy: { text: '5 дн назад' },
  nutrition: { text: '420 ккал' },
  glp1: { text: 'через 5 дн' },
  hrt: { text: 'неделя 9 из 12' },
  labs: { text: '1 вне нормы', tone: 'bad' },
  genetics: { text: 'VCF · 14 правил' },
  supplements: { text: '3 активных' },
  skincare: { text: 'утро ✓' },
  interactions: { text: '1 срабатывает', tone: 'bad' },
  signals: { text: 'сегодня' },
  timeline: { text: '' },
  reports: { text: 'дайджест вс' },
  charts: { text: '4' },
}

/** The two account rows under the sections. */
export const moreSystemFixture: Record<'share' | 'settings', MoreStatus> = {
  share: { text: 'отчёт по ссылке' },
  settings: { text: '16 из 16' },
}
