import { useState } from 'react'
import { useSuspenseQuery } from '@tanstack/react-query'
import { api, ok } from '@/api/client'
import { Disclosure } from '@/components/controls/Disclosure'
import { Section } from '@/components/controls/Section'
import { Headline, TopBar } from '@/components/shell/PageHead'
import { useT } from '@/i18n/useT'
import { parseIsoDate, shortDate } from '@/lib/dates'
import { clockTime, formatInt, formatNumber } from '@/lib/format'
import type { components } from '@/api/schema'
import { hasDetail, lapTime, ZONE_COLOR } from './activity'
import './recovery.css'

type ActivitiesListView = components['schemas']['ActivitiesListView']
type ActivityItem = components['schemas']['ActivityItem']

export default function ActivitiesScreen() {
  const { t, tOr, lang } = useT()
  const [open, setOpen] = useState<string | null>(null)

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
                    {a.activity_type && tOr(`garmin.activity.${a.activity_type}`, a.activity_type) !== a.name && (
                      <div className="m">{tOr(`garmin.activity.${a.activity_type}`, a.activity_type)}</div>
                    )}
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
                {hasDetail(a) && (
                  <Disclosure open={open === a.id} onToggle={() => setOpen(open === a.id ? null : a.id)} title={t('app.activity.details')} className="act-more">
                    <ActivityDetail a={a} />
                  </Disclosure>
                )}
              </div>
            )
          })}
        </div>
      </Section>
    </>
  )
}

function ActivityDetail({ a }: { a: ActivityItem }) {
  const { t, lang } = useT()
  const chips: { label: string; value: string }[] = []
  if (a.training_effect_aerobic != null) chips.push({ label: t('app.activity.te_aerobic'), value: formatNumber(a.training_effect_aerobic, lang, 1) })
  if (a.training_effect_anaerobic != null) chips.push({ label: t('app.activity.te_anaerobic'), value: formatNumber(a.training_effect_anaerobic, lang, 1) })
  if (a.elevation_gain_meters != null) chips.push({ label: t('app.activity.elevation'), value: `${formatInt(a.elevation_gain_meters, lang)} ${t('app.unit.m')}` })
  if (a.avg_power != null) chips.push({ label: t('app.activity.power'), value: `${formatInt(a.avg_power, lang)} ${t('app.unit.w')}` })
  const zoneMax = Math.max(1, ...a.hr_zones.map((z) => z.seconds))

  return (
    <div className="act-d">
      {chips.length > 0 && (
        <div className="act-chips">
          {chips.map((c) => (
            <span key={c.label}>
              {c.label} <b className="num">{c.value}</b>
            </span>
          ))}
        </div>
      )}
      {a.hr_zones.length > 0 && (
        <div className="act-block">
          <div className="act-cap">{t('app.activity.hr_zones')}</div>
          {a.hr_zones.map((z) => (
            <div key={z.zone} className="zone-row">
              <span className="m num">{t('app.activity.zone', { n: z.zone })}</span>
              <div className="zbar">
                <i style={{ width: `${Math.round((z.seconds / zoneMax) * 100)}%`, background: ZONE_COLOR[z.zone - 1] ?? 'var(--muted)' }} />
              </div>
              <span className="m num zone-min">{t('app.duration.min', { m: Math.round(z.seconds / 60) })}</span>
            </div>
          ))}
        </div>
      )}
      {a.splits.length > 1 && (
        <div className="act-block spl">
          <div className="act-cap">{t('app.activity.splits')}</div>
          <div className="spl-r spl-h">
            <span>#</span>
            <span>{t('app.activity.split_distance')}</span>
            <span>{t('app.activity.split_time')}</span>
            <span>{t('app.activity.split_hr')}</span>
          </div>
          {a.splits.map((sp) => (
            <div key={sp.index} className="spl-r num">
              <span>{sp.index}</span>
              <span>{sp.distance_meters ? `${formatNumber(sp.distance_meters / 1000, lang, 2)} ${t('app.unit.km')}` : '—'}</span>
              <span>{sp.duration_seconds ? lapTime(sp.duration_seconds) : '—'}</span>
              <span>{sp.avg_hr ?? '—'}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
