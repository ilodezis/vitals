import { useQuery } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { api } from '@/api/client'
import { Section } from '@/components/controls/Section'
import { Icon } from '@/components/icons/Icon'
import { Headline, TopBar } from '@/components/shell/PageHead'
import { useT } from '@/i18n/useT'
import { longDate, parseIsoDate } from '@/lib/dates'
import type { components } from '@/api/schema'
import './recovery.css'

type NightsListView = components['schemas']['NightsListView']

export default function NightsListScreen() {
  const { t, lang } = useT()

  const { data, isLoading } = useQuery({
    queryKey: ['recovery', 'nights'],
    queryFn: async (): Promise<NightsListView> => {
      const res = await api.GET('/api/v1/recovery/nights', { params: { query: { limit: 60 } } })
      if (!res.data) throw new Error('Nights list unavailable')
      return res.data
    },
  })

  const nights = data?.nights ?? []
  const n0 = nights[0]

  const fmtHM = (seconds: number) => {
    const mins = Math.round(seconds / 60)
    const h = Math.floor(mins / 60)
    const m = mins % 60
    return h > 0 ? `${h} ч ${m} мин` : `${m} мин`
  }

  return (
    <>
      <TopBar title={t('app.title.nights')} />
      <Headline title="Сон" />

      {/* Hero row for the latest night */}
      {n0 && (
        <Section>
          <Link to="/recovery/sleep/$date" params={{ date: n0.date }} className="hero-row">
            <div className="hr-l">
              <div className="sub">Прошлая ночь</div>
              <div className="hr-t">{longDate(parseIsoDate(n0.date), lang)}</div>
              <div className="sub num">{fmtHM(n0.duration_seconds ?? 0)}</div>
            </div>
            <div className="hr-f">
              <div className="f">
                <div className="f-v">{n0.score ?? '—'}</div>
                <div className="f-l">Оценка сна</div>
              </div>
            </div>
            <Icon name="chevR" />
            <div className="compo">
              <i style={{ flex: n0.deep_seconds ?? 0, background: 'var(--deep)' }} />
              <i style={{ flex: n0.light_seconds ?? 0, background: 'var(--cool)' }} />
              <i style={{ flex: n0.rem_seconds ?? 0, background: 'var(--violet)' }} />
              <i style={{ flex: n0.awake_seconds ?? 0, background: 'var(--bad)' }} />
            </div>
          </Link>
        </Section>
      )}

      {/* Nights table */}
      <Section title={`История ночей (${nights.length})`}>
        <div className="rows">
          {isLoading && <div className="row"><span className="m">Загрузка...</span></div>}
          {!isLoading && nights.length === 0 && <div className="row"><span className="m">{t('app.empty')}</span></div>}
          {nights.map((n) => (
            <Link key={n.date} to="/recovery/sleep/$date" params={{ date: n.date }} className="row r-night">
              <span className="t num">{longDate(parseIsoDate(n.date), lang)}</span>
              <span className="m num">{fmtHM(n.duration_seconds ?? 0)}</span>
              <span className="v">{n.score ?? '—'}</span>
              <div className="compo mini" style={{ width: 80 }}>
                <i style={{ flex: n.deep_seconds ?? 0, background: 'var(--deep)' }} />
                <i style={{ flex: n.light_seconds ?? 0, background: 'var(--cool)' }} />
                <i style={{ flex: n.rem_seconds ?? 0, background: 'var(--violet)' }} />
                <i style={{ flex: n.awake_seconds ?? 0, background: 'var(--bad)' }} />
              </div>
              <Icon name="chevR" />
            </Link>
          ))}
        </div>
      </Section>
    </>
  )
}
