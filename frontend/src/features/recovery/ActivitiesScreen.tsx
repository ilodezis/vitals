import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '@/api/client'
import { Section } from '@/components/controls/Section'
import { Icon } from '@/components/icons/Icon'
import { Headline, TopBar } from '@/components/shell/PageHead'
import { useT } from '@/i18n/useT'
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
    return `${mins} мин`
  }

  const fmtDistance = (m?: number | null) => {
    if (!m) return '—'
    const km = m / 1000
    return `${formatNumber(km, lang, 2)} км`
  }

  return (
    <>
      <TopBar title={t('app.title.activities')} />
      <Headline title="Активности" />

      <Section>
        <div className="acts-list">
          {isLoading && <div className="row"><span className="m">Загрузка...</span></div>}
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
                  <span className="m num">{a.start_time.slice(0, 16).replace('T', ' ')}</span>
                </div>

                <div className="act-s">
                  <div>
                    <b className="num">{fmtDuration(a.duration_seconds)}</b>
                    <small>Длительность</small>
                  </div>
                  <div>
                    <b className="num">{fmtDistance(a.distance_meters)}</b>
                    <small>Дистанция</small>
                  </div>
                  <div>
                    <b className="num">{a.calories != null ? `${a.calories} ккал` : '—'}</b>
                    <small>Калории</small>
                  </div>
                  <div>
                    <b className="num">
                      {a.avg_hr ?? '—'}{a.max_hr ? ` / ${a.max_hr}` : ''}
                    </b>
                    <small>Пульс ср. / макс.</small>
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
