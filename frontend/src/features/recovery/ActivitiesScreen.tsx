import { useSuspenseQuery } from '@tanstack/react-query'
import { api, ok } from '@/api/client'
import { Section } from '@/components/controls/Section'
import { Headline, TopBar } from '@/components/shell/PageHead'
import { useT } from '@/i18n/useT'
import { parseIsoDate, shortDate } from '@/lib/dates'
import { clockTime, formatInt, formatNumber } from '@/lib/format'
import type { components } from '@/api/schema'
import './recovery.css'

type ActivitiesListView = components['schemas']['ActivitiesListView']

export default function ActivitiesScreen() {
  const { t, lang } = useT()

  const { data } = useSuspenseQuery({
    queryKey: ['recovery', 'activities'],
    queryFn: async (): Promise<ActivitiesListView> => ok(api.GET('/api/v1/recovery/activities', { params: { query: { limit: 30 } } })),
  })

  const activities = data.activities ?? []

  const fmtDuration = (sec: number) => {
    const mins = Math.round(sec / 60)
    return t('app.duration.min', { m: mins })
  }

  const fmtDistance = (m?: number | null) => {
    if (!m) return '—'
    const km = m / 1000
    return `${formatNumber(km, lang, 2)} ${t('app.unit.km')}`
  }

  return (
    <>
      <TopBar title={t('app.title.activities')} />
      <Headline title={t('app.title.activities')} />

      <Section>
        <div className="acts-list">
          {activities.length === 0 && (
            <div className="row"><span className="m">{t('app.empty')}</span></div>
          )}
          {activities.map((a) => {
            return (
              <div key={a.id} className="panel act">
                <div className="act-h">
                  <div>
                    <div className="act-t">{a.name}</div>
                    {a.activity_type && a.activity_type !== a.name && <div className="m">{a.activity_type}</div>}
                  </div>
                  <span className="m num">
                    {shortDate(parseIsoDate(a.start_time), lang)} {clockTime(a.start_time.slice(11))}
                  </span>
                </div>

                <div className="act-s">
                  <div>
                    <b className="num">{fmtDuration(a.duration_seconds)}</b>
                    <small>{t('app.activity.duration')}</small>
                  </div>
                  <div>
                    <b className="num">{fmtDistance(a.distance_meters)}</b>
                    <small>{t('app.activity.distance')}</small>
                  </div>
                  <div>
                    <b className="num">{a.calories != null ? t('app.unit.kcal_value', { value: formatInt(a.calories, lang) }) : '—'}</b>
                    <small>{t('app.activity.calories')}</small>
                  </div>
                  <div>
                    <b className="num">
                      {a.avg_hr ?? '—'}{a.max_hr ? ` / ${a.max_hr}` : ''}
                    </b>
                    <small>{t('app.activity.hr_avg_max')}</small>
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      </Section>
    </>
  )
}
