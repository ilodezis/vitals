import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { I18nProvider } from '@/i18n/I18nProvider'
import type { WeightHistoryRow } from './types'
import { filterVisibleHistoryRows, WeightHistory } from './WeightHistory'

const DICTIONARY = {
  'app.today_word': 'сегодня',
  'app.yesterday_word': 'вчера',
  'app.unit.kg': 'кг',
  'app.source.manual': 'Вручную',
  'app.source.garmin': 'Garmin',
  'common.edit': 'Изменить',
  'common.delete': 'Удалить',
  'app.weight.show_superseded_n': 'ещё {count} перекрыто · показать',
  'app.weight.hide_superseded': 'скрыть перекрытые',
  'app.weight.superseded_by_manual': 'Перекрыто ручным вводом',
  'app.weight.superseded': 'Перекрыто',
}

const ROWS: WeightHistoryRow[] = [
  {
    id: 1,
    date: '2026-09-30',
    time: '08:15',
    kg: 84.5,
    source: 'manual',
    note: 'утренний замер',
  },
  {
    id: 2,
    date: '2026-09-30',
    time: '07:30',
    kg: 84.9,
    source: 'garmin',
    superseded: true,
    supersededBy: 'manual',
  },
  {
    id: 3,
    date: '2026-09-29',
    time: '08:00',
    kg: 84.8,
    source: 'manual',
  },
]

function render(rows: readonly WeightHistoryRow[]) {
  return renderToStaticMarkup(
    <QueryClientProvider client={new QueryClient()}>
      <I18nProvider lang="ru" dictionary={DICTIONARY}>
        <WeightHistory rows={rows} />
      </I18nProvider>
    </QueryClientProvider>,
  )
}

describe('filterVisibleHistoryRows', () => {
  it('hides superseded rows when showSuperseded is false', () => {
    const visible = filterVisibleHistoryRows(ROWS, false)
    expect(visible.map((r) => r.id)).toEqual([1, 3])
  })

  it('keeps all rows when showSuperseded is true', () => {
    const visible = filterVisibleHistoryRows(ROWS, true)
    expect(visible.map((r) => r.id)).toEqual([1, 2, 3])
  })
})

describe('WeightHistory component', () => {
  it('renders all rows and no toggle button when no rows are superseded', () => {
    const activeOnly = [ROWS[0]!, ROWS[2]!]
    const html = render(activeOnly)
    expect(html).toContain('утренний замер')
    expect(html).not.toContain('superseded-toggle')
  })

  it('collapses superseded rows by default and renders toggle with count', () => {
    const html = render(ROWS)
    // Superseded row data must NOT be rendered in DOM by default
    expect(html).not.toContain('07:30')
    expect(html).not.toContain('Перекрыто ручным вводом')

    // Active rows are rendered
    expect(html).toContain('утренний замер')
    expect(html).toContain('08:15')

    // Toggle button is rendered with count
    expect(html).toContain('superseded-toggle')
    expect(html).toContain('ещё 1 перекрыто · показать')
  })
})
