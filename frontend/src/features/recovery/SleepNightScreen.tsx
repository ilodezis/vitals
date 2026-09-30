import { useMemo, useState } from 'react'
import { useParams, useNavigate } from '@tanstack/react-router'
import { useQuery } from '@tanstack/react-query'
import { api } from '@/api/client'
import { Segmented } from '@/components/controls/Segmented'
import { Section } from '@/components/controls/Section'
import { Hypnogram } from '@/components/charts/Hypnogram'
import { Icon } from '@/components/icons/Icon'
import { Headline, TopBar } from '@/components/shell/PageHead'
import { useT } from '@/i18n/useT'
import { longDate, parseIsoDate, toIsoDate } from '@/lib/dates'
import { formatNumber } from '@/lib/format'
import type { components } from '@/api/schema'
import './recovery.css'

type SleepNightView = components['schemas']['SleepNightView']

export default function SleepNightScreen() {
  const { t, lang } = useT()
  const navigate = useNavigate()
  const params = useParams({ strict: false }) as { date?: string }
  const selectedDate = params.date || toIsoDate(new Date())

  const { data: night, isLoading } = useQuery({
    queryKey: ['recovery', 'sleep', selectedDate],
    queryFn: async (): Promise<SleepNightView> => {
      const { data } = await api.GET('/api/v1/recovery/sleep/{on_date}', {
        params: { path: { on_date: selectedDate } },
      })
      if (!data) throw new Error('Sleep night data unavailable')
      return data
    },
  })

  const [activeCurveGroup, setActiveCurveGroup] = useState<'pulse' | 'breathing' | 'movement'>('pulse')

  const stageMins = useMemo(() => {
    if (!night?.stages_minutes) return { deep: 0, light: 0, rem: 0, awake: 0 }
    return {
      deep: night.stages_minutes.deep ?? 0,
      light: night.stages_minutes.light ?? 0,
      rem: night.stages_minutes.rem ?? 0,
      awake: night.stages_minutes.awake ?? 0,
    }
  }, [night?.stages_minutes])

  // Start minutes since midnight for Hypnogram
  const startMinutes = useMemo(() => {
    if (!night?.start_time) return 23 * 60
    const [hh, mm] = night.start_time.split(':').map((s) => parseInt(s, 10))
    return (hh || 0) * 60 + (mm || 0)
  }, [night?.start_time])

  // Convert stage series to 5-minute blocks for Hypnogram
  const stagesArray = useMemo(() => {
    if (!night?.stages_series || night.stages_series.length === 0) {
      return [2, 2, 3, 3, 3, 1, 1, 2, 2, 3, 1, 0] // fallback blocks
    }
    const blocks: number[] = []
    const stageMap: Record<string, number> = { awake: 0, rem: 1, light: 2, deep: 3 }
    for (const seg of night.stages_series) {
      const stageCode = stageMap[seg.stage.toLowerCase()] ?? 2
      const blockCount = Math.max(1, Math.round(seg.duration_min / 5))
      for (let i = 0; i < blockCount; i++) blocks.push(stageCode)
    }
    return blocks
  }, [night?.stages_series])

  // Active curve points
  const activeSeries = useMemo(() => {
    if (!night) return []
    if (activeCurveGroup === 'pulse') {
      return [
        { label: t('app.sleep.curve.heart_rate'), color: '#F4F0F6', points: night.heart_rate ?? [] },
        { label: t('app.sleep.curve.hrv'), color: '#BCA4DC', points: night.hrv ?? [] },
      ]
    }
    if (activeCurveGroup === 'breathing') {
      return [
        { label: t('app.sleep.curve.respiration'), color: '#6FB6C9', points: night.respiration ?? [] },
      ]
    }
    return [
      { label: t('app.sleep.curve.movement'), color: '#F0B24A', points: night.movement ?? [] },
    ]
  }, [night, activeCurveGroup, t])

  const fmtHM = (mins: number) => {
    const h = Math.floor(mins / 60)
    const m = mins % 60
    return h > 0 ? t('app.duration.hm', { h, m }) : t('app.duration.min', { m })
  }

  if (isLoading || !night) {
    return (
      <>
        <TopBar title={t('app.title.sleep')} />
        <Headline title={t('app.title.sleep')} />
        <div style={{ padding: '24px', color: 'var(--muted)' }}>{t('app.loading')}</div>
      </>
    )
  }

  const dateObj = parseIsoDate(night.date)

  return (
    <>
      <TopBar title={t('app.title.sleep')} />
      <Headline title={longDate(dateObj, lang)}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', width: '100%' }}>
          <div className="fig-hero">
            <div className="big" data-fig="sleep">
              <span className="num">{night.score ?? '—'}</span>
            </div>
            <div className="side">
              <span className="sub">
                {night.rhr ? t('app.sleep.sleeping_rhr', { rhr: formatNumber(night.rhr, lang) }) : ''}
              </span>
              <span className="sub">
                {night.spo2_min ? t('app.sleep.min_spo2', { spo2: formatNumber(night.spo2_min, lang) }) : ''}
                {night.bb_change ? t('app.sleep.bb_change', { change: formatNumber(night.bb_change, lang) }) : ''}
              </span>
            </div>
          </div>
          <div style={{ display: 'flex', gap: '8px' }}>
            <button
              type="button"
              className="ibtn"
              disabled={!night.prev_date}
              onClick={() => night.prev_date && navigate({ to: '/recovery/sleep/$date', params: { date: night.prev_date } })}
              aria-label={t('app.sleep.prev_night')}
            >
              <Icon name="chevL" />
            </button>
            <button
              type="button"
              className="ibtn"
              disabled={!night.next_date}
              onClick={() => night.next_date && navigate({ to: '/recovery/sleep/$date', params: { date: night.next_date } })}
              aria-label={t('app.sleep.next_night')}
            >
              <Icon name="chevR" />
            </button>
          </div>
        </div>
      </Headline>

      {(night.awake_count != null || night.restless_moments != null) && (
        <p className="night-note">
          {t('app.sleep.awakenings_and_restless', { awake: night.awake_count ?? 0, restless: night.restless_moments ?? 0 })}
        </p>
      )}

      {/* Sleep Stages Section */}
      <Section
        title={t('app.sleep.stages_title')}
        meta={night.start_time && night.end_time ? `${night.start_time} → ${night.end_time}` : undefined}
      >
        <div className="panel bare">
          <Hypnogram stages={stagesArray} startMinutes={startMinutes} />

          {/* Phase bar */}
          <div className="compo">
            <i style={{ flex: stageMins.deep, background: 'var(--deep)' }} />
            <i style={{ flex: stageMins.light, background: 'var(--cool)' }} />
            <i style={{ flex: stageMins.rem, background: 'var(--violet)' }} />
            <i style={{ flex: stageMins.awake, background: 'var(--bad)' }} />
          </div>

          {/* Legend */}
          <div className="hyp-legend">
            <div>
              <i style={{ background: 'var(--deep)' }} />
              {t('app.stage.deep')}
              <b>{fmtHM(stageMins.deep)}</b>
            </div>
            <div>
              <i style={{ background: 'var(--cool)' }} />
              {t('app.stage.light')}
              <b>{fmtHM(stageMins.light)}</b>
            </div>
            <div>
              <i style={{ background: 'var(--violet)' }} />
              {t('app.stage.rem')}
              <b>{fmtHM(stageMins.rem)}</b>
            </div>
            <div>
              <i style={{ background: 'var(--bad)' }} />
              {t('app.stage.awake')}
              <b>{t('app.duration.min', { m: stageMins.awake })}</b>
            </div>
          </div>
        </div>
      </Section>

      {/* Overnight Curves Section */}
      <Section title={t('app.sleep.metrics_title')}>
        <div className="panel bare">
          <div className="panel-h" style={{ padding: '16px 16px 0' }}>
            <Segmented
              value={activeCurveGroup}
              onChange={setActiveCurveGroup}
              label={t('app.sleep.metrics_label')}
              options={[
                { id: 'pulse', label: t('app.sleep.tab_pulse') },
                { id: 'breathing', label: t('app.sleep.tab_breathing') },
                { id: 'movement', label: t('app.sleep.tab_movement') },
              ]}
            />
          </div>

          <div style={{ padding: '16px' }}>
            <div style={{ display: 'flex', gap: '16px', marginBottom: '12px' }}>
              {activeSeries.map((s) => (
                <span key={s.label} style={{ fontSize: 'var(--t-label)', color: 'var(--fg-2)', display: 'inline-flex', alignItems: 'center', gap: '6px' }}>
                  <i style={{ width: 8, height: 8, borderRadius: 2, background: s.color, display: 'inline-block' }} />
                  {s.label}
                </span>
              ))}
            </div>

            {/* SVG line chart */}
            <div style={{ height: 180, width: '100%', position: 'relative' }}>
              <svg width="100%" height="100%" viewBox="0 0 400 180" preserveAspectRatio="none">
                <line x1="0" y1="90" x2="400" y2="90" stroke="var(--line)" strokeDasharray="3 3" />
                {activeSeries.map((s, sIdx) => {
                  if (s.points.length === 0) return null
                  const vals = s.points.map((p) => p.value)
                  const minV = Math.min(...vals)
                  const maxV = Math.max(...vals)
                  const rangeV = maxV - minV || 1
                  const pathData = s.points
                    .map((p, pIdx) => {
                      const x = (pIdx / (s.points.length - 1 || 1)) * 400
                      const y = 160 - ((p.value - minV) / rangeV) * 140
                      return `${pIdx === 0 ? 'M' : 'L'} ${x.toFixed(1)} ${y.toFixed(1)}`
                    })
                    .join(' ')
                  return (
                    <path
                      key={sIdx}
                      d={pathData}
                      fill="none"
                      stroke={s.color}
                      strokeWidth="2"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                  )
                })}
              </svg>
            </div>
          </div>
        </div>
      </Section>
    </>
  )
}
