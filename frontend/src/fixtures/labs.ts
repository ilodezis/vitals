import type { LabMarker, LabsView } from '@/features/labs/types'

const hist = (a: number, b: number, c: number): LabMarker['history'] => [
  { dateIso: '2026-03-12', value: a },
  { dateIso: '2026-06-04', value: b },
  { dateIso: '2026-09-06', value: c },
]

export const labsFixture: LabsView = {
  collectedIso: '2026-09-06',
  lab: 'Инвитро',
  source: 'PDF',
  markers: [
    { id: 'vitd', name: 'Витамин D (25-OH)', groupKey: 'vitamins', group: 'Витамины', unit: 'нг/мл', value: 28, lo: 30, hi: 100, min: 0, max: 120, decimals: 0, history: hist(19, 24, 28) },
    { id: 'tg', name: 'Триглицериды', groupKey: 'metabolism', group: 'Метаболизм', unit: 'мг/дл', value: 128, lo: 0, hi: 150, min: 0, max: 250, decimals: 0, history: hist(164, 141, 128) },
    { id: 'hba1c', name: 'HbA1c', groupKey: 'metabolism', group: 'Метаболизм', unit: '%', value: 5.3, lo: 4.0, hi: 5.7, min: 3.5, max: 7, decimals: 1, history: hist(5.6, 5.4, 5.3) },
    { id: 'glu', name: 'Глюкоза натощак', groupKey: 'metabolism', group: 'Метаболизм', unit: 'ммоль/л', value: 5.1, lo: 3.9, hi: 5.8, min: 3, max: 7.5, decimals: 1, history: hist(5.6, 5.3, 5.1) },
    { id: 'ins', name: 'Инсулин натощак', groupKey: 'metabolism', group: 'Метаболизм', unit: 'мкЕд/мл', value: 8.3, lo: 2.6, hi: 24.9, min: 0, max: 30, decimals: 1, history: hist(14.2, 10.9, 8.3) },
    { id: 'tsh', name: 'ТТГ', groupKey: 'hormones', group: 'Гормоны', unit: 'мМЕ/л', value: 2.1, lo: 0.4, hi: 4.0, min: 0, max: 5, decimals: 1, history: hist(2.4, 2.2, 2.1) },
    { id: 'tt', name: 'Тестостерон общий', groupKey: 'hormones', group: 'Гормоны', unit: 'нмоль/л', value: 21.4, lo: 8.6, hi: 29.0, min: 0, max: 35, decimals: 1, history: hist(17.9, 19.6, 21.4) },
    { id: 'fer', name: 'Ферритин', groupKey: 'vitamins', group: 'Витамины', unit: 'нг/мл', value: 96, lo: 30, hi: 400, min: 0, max: 450, decimals: 0, history: hist(88, 101, 96) },
  ],
}
