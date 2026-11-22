import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { I18nProvider } from '@/i18n/I18nProvider'
import {
  buildLlmExportUrl,
  DataSection,
  llmExportFilename,
  pressRestart,
  resolveLlmExportRange,
} from './DataSection'

const DICTIONARY = {
  'settings.export_label': 'Export',
  'settings.export_llm_title': 'Export for AI',
  'settings.export_llm_hint': 'Flat JSON for chat.',
  'settings.export_llm_period': 'Period',
  'settings.export_llm_period_all': 'All time',
  'settings.export_llm_period_days': '{n} days',
  'settings.export_llm_period_custom': 'Exact range',
  'settings.export_llm': 'Export for AI (.json)',
  'settings.export_full_title': 'Full backup',
  'settings.export_full_hint': 'All history.',
  'settings.export_full': 'Full backup (.json)',
  'settings.restart_title': 'Container restart',
  'settings.restart_hint': 'Restarts the container.',
  'settings.restart_text': 'Restarting the app…',
  'settings.restart_btn': 'Restart container',
  'common.confirm_question': 'Sure?',
}

function render() {
  return renderToStaticMarkup(
    <QueryClientProvider client={new QueryClient()}>
      <I18nProvider lang="en" dictionary={DICTIONARY}>
        <DataSection />
      </I18nProvider>
    </QueryClientProvider>,
  )
}

describe('restart step', () => {
  it('asks first, restarts on the second press, and ignores presses while it runs', () => {
    expect(pressRestart('idle')).toEqual({ phase: 'confirm', fire: false })
    expect(pressRestart('confirm')).toEqual({ phase: 'restarting', fire: true })
    expect(pressRestart('restarting')).toEqual({ phase: 'restarting', fire: false })
  })
})

describe('LLM export period resolution', () => {
  const today = '2026-11-23'

  it('computes inclusive calendar-day windows for presets', () => {
    expect(resolveLlmExportRange('7', today, '', '')).toEqual({
      ok: true,
      range: { since: '2026-11-17', until: '2026-11-23' },
    })
    expect(resolveLlmExportRange('30', today, '', '')).toEqual({
      ok: true,
      range: { since: '2026-10-25', until: '2026-11-23' },
    })
    expect(resolveLlmExportRange('90', today, '', '')).toEqual({
      ok: true,
      range: { since: '2026-08-26', until: '2026-11-23' },
    })
    expect(resolveLlmExportRange('365', today, '', '')).toEqual({
      ok: true,
      range: { since: '2025-11-24', until: '2026-11-23' },
    })
  })

  it('leaves bounds open for all-time export', () => {
    expect(resolveLlmExportRange('all', today, '2026-01-01', '2026-02-01')).toEqual({
      ok: true,
      range: {},
    })
  })

  it('accepts exact, open-ended, and single-day custom ranges and rejects empty or inverted ones', () => {
    expect(resolveLlmExportRange('custom', today, '2026-10-01', '2026-10-31')).toEqual({
      ok: true,
      range: { since: '2026-10-01', until: '2026-10-31' },
    })
    expect(resolveLlmExportRange('custom', today, '2026-10-15', '2026-10-15')).toEqual({
      ok: true,
      range: { since: '2026-10-15', until: '2026-10-15' },
    })
    expect(resolveLlmExportRange('custom', today, '2026-10-01', '')).toEqual({
      ok: true,
      range: { since: '2026-10-01' },
    })
    expect(resolveLlmExportRange('custom', today, '', '2026-10-31')).toEqual({
      ok: true,
      range: { until: '2026-10-31' },
    })
    expect(resolveLlmExportRange('custom', today, '', '')).toEqual({
      ok: false,
      error: 'need_date',
    })
    expect(resolveLlmExportRange('custom', today, '2026-10-31', '2026-10-01')).toEqual({
      ok: false,
      error: 'bad_period',
    })
  })

  it('builds query URLs and filenames matching the range bounds', () => {
    expect(buildLlmExportUrl({})).toBe('/api/v1/settings/export-llm')
    expect(buildLlmExportUrl({ since: '2026-10-01', until: '2026-10-31' })).toBe(
      '/api/v1/settings/export-llm?since=2026-10-01&until=2026-10-31',
    )
    expect(buildLlmExportUrl({ since: '2026-10-01' })).toBe('/api/v1/settings/export-llm?since=2026-10-01')
    expect(buildLlmExportUrl({ until: '2026-10-31' })).toBe('/api/v1/settings/export-llm?until=2026-10-31')

    expect(llmExportFilename({}, today)).toBe('vitals_llm_2026-11-23.json')
    expect(llmExportFilename({ since: '2026-10-01', until: '2026-10-31' }, today)).toBe(
      'vitals_llm_2026-10-01_2026-10-31.json',
    )
    expect(llmExportFilename({ since: '2026-10-01' }, today)).toBe('vitals_llm_from_2026-10-01.json')
    expect(llmExportFilename({ until: '2026-10-31' }, today)).toBe('vitals_llm_until_2026-10-31.json')
  })
})

describe('DataSection', () => {
  it('describes the restart instead of claiming one is running', () => {
    const html = render()
    expect(html).toContain('Restarts the container.')
    expect(html).not.toContain('Restarting the app')
  })

  it('renders the AI export period selector presets alongside full backup', () => {
    const html = render()
    expect(html).toContain('7 days')
    expect(html).toContain('30 days')
    expect(html).toContain('90 days')
    expect(html).toContain('365 days')
    expect(html).toContain('All time')
    expect(html).toContain('Exact range')
    expect(html).toContain('Full backup (.json)')
  })

  it('keeps the secondary actions off the amber button style', () => {
    expect(render()).not.toMatch(/class="([^"]* )?btn( [^"]*)?"/)
  })
})
