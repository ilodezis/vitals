import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '@/api/client'
import { Section } from '@/components/controls/Section'
import { Icon } from '@/components/icons/Icon'
import { Headline, TopBar } from '@/components/shell/PageHead'
import { useT } from '@/i18n/useT'
import { parseIsoDate, shortDate } from '@/lib/dates'
import { formatNumber } from '@/lib/format'
import type { components } from '@/api/schema'
import './recovery.css'

type ActivitiesListView = components['schemas']['ActivitiesListView']

export default function ActivitiesScreen() {
  const { t, lang } = useT()
  const [openId, setOpenId] = useState<string | null>(null)

  const { data, isLoading } = useQuery({
    queryKey: ['recovery', 'activities'],
    queryFn: async (): Promise<ActivitiesListView> => {
      const res = await api.GET('/api/v1/recovery/activities', { params: { query: { limit: 30 } } })
      if (!res.data) throw new Error('Activities list unavailable')
      return res.data
    },
  })

  const activities = data?.activities ?? []

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
          {isLoading && <div className="row"><span className="m">{t('app.loading')}</span></div>}
          {!isLoading && activities.length === 0 && (
            <div className="row"><span className="m">{t('app.empty')}</span></div>
          )}
          {activities.map((a) => {
            const isOpen = openId === a.id
            return (
              <div key={a.id} className="panel" style={{ padding: '16px' }}>
                <div
                  className="act-h"
                  onClick={() => setOpenId(isOpen ? null : a.id)}
                  style={{ cursor: 'pointer' }}
                  role="button"
                  tabIndex={0}
                >
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    <Icon name={isOpen ? 'chevD' : 'chevR'} />
                    <div>
                      <div className="t" style={{ fontWeight: 600 }}>{a.name}</div>
                      {a.activity_type && a.activity_type !== a.name && (
                        <div className="m">{a.activity_type}</div>
                      )}
                    </div>
                  </div>
                  <span className="m num">{shortDate(parseIsoDate(a.start_time), lang)} {a.start_time.slice(11, 16)}</span>
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
                    <b className="num">{a.calories != null ? `${formatNumber(a.calories, lang)} ${t('app.unit.kcal')}` : '—'}</b>
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
