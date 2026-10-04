import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { live } from '@/fixtures/environment'
import { I18nProvider } from '@/i18n/I18nProvider'
import { loadDictionary } from '@/i18n/load'
import { NowSection } from './NowSection'
import type { EnvLive } from './types'

const ru = await loadDictionary('ru')
const en = await loadDictionary('en')

function render(data: EnvLive, over: { vitalsAway?: boolean; lang?: 'ru' | 'en'; nowMs?: number } = {}): string {
  const lang = over.lang ?? 'ru'
  return renderToStaticMarkup(
    <QueryClientProvider client={new QueryClient()}>
      <I18nProvider lang={lang} dictionary={lang === 'ru' ? ru : en}>
        <NowSection live={data} answeredAt={1_000_000} nowMs={over.nowMs ?? 1_004_000} vitalsAway={over.vitalsAway ?? false} />
      </I18nProvider>
    </QueryClientProvider>,
  )
}

describe('NowSection', () => {
  it('shows CO₂ large in the colour of its zone, with a word for it and the trend', () => {
    const html = render(live({ now: { co2_ppm: 1106, co2_zone: 'warn', co2_trend_ppm_per_h: 144 } }))
    expect(html).toContain('data-zone="warn"')
    expect(html).toContain('Душно')
    expect(html).toContain('растёт')
    expect(html).toContain('+144 ppm/ч')
    expect(html).toMatch(/1\D?106/)
  })

  it('says steady for a small drift, with no arrow', () => {
    const html = render(live({ now: { co2_trend_ppm_per_h: 8 } }))
    expect(html).toContain('стабильно')
    expect(html).not.toContain('ppm/ч')
  })

  it('has no trend when the server could not give one', () => {
    expect(render(live({ now: { co2_trend_ppm_per_h: null } }))).not.toContain('env-trend')
  })

  it('names how fresh the reading is and the Wi-Fi signal', () => {
    const html = render(live({ station: { age_s: 4 } }), { nowMs: 1_009_000 })
    expect(html).toContain('Станция на связи')
    expect(html).toContain('обновлено 13 с назад')
    expect(html).toContain('−61 дБм')
  })

  it('says "just now" for a reading a moment old', () => {
    expect(render(live({ station: { age_s: 0 } }), { nowMs: 1_001_000 })).toContain('обновлено только что')
  })

  it('warns that a quiet station’s numbers are its last, and still shows them', () => {
    const html = render(live({ station: { status: 'stale', age_s: 420 }, now: { co2_ppm: 1100, co2_zone: 'warn' } }))
    expect(html).toContain('Станция молчит')
    expect(html).toContain('Цифры — её последние показания')
    expect(html).toContain('data-zone="warn"')
  })

  it('greys a station that has stopped: no zone colour, no verdicts, the way to fix it', () => {
    const html = render(live({ station: { status: 'offline', age_s: 5400, last_seen_at: '2026-10-05T10:00:00Z' } }))
    expect(html).toContain('env-now dim')
    expect(html).toContain('data-zone="none"')
    expect(html).toContain('её последнее значение')
    expect(html).not.toContain('Комфортно')
    expect(html).toContain('Проверь питание и Wi-Fi')
  })

  it('does not pass a reading it can no longer renew off as live', () => {
    const html = render(live(), { vitalsAway: true })
    expect(html).toContain('Нет связи с Vitals')
    expect(html).toContain('env-now dim')
  })

  it('writes a dash for what the sensor has not given yet', () => {
    const html = render(live({ now: { co2_ppm: null, temperature_c: null, humidity_pct: null, co2_zone: 'none', co2_trend_ppm_per_h: null } }))
    expect(html).toContain('—')
    expect(html).not.toContain('Комфортно')
  })

  it('judges temperature and humidity by the owner’s ranges', () => {
    const html = render(live({ now: { temperature_c: 27.5, humidity_pct: 25 } }))
    expect(html).toContain('Жарковато')
    expect(html).toContain('Сухо')
  })

  it('reads in English too', () => {
    const html = render(live({ now: { co2_ppm: 1650, co2_zone: 'bad' } }), { lang: 'en' })
    expect(html).toContain('Poor')
    expect(html).toContain('Station online')
    expect(html).toContain('updated 8 s ago')
  })
})
