import { useDeferredValue, useMemo, useState } from 'react'
import { useParams, useNavigate } from '@tanstack/react-router'
import { useSuspenseQuery } from '@tanstack/react-query'
import { api, ok } from '@/api/client'
import { useTodayIso } from '@/app/session'
import { Alert } from '@/components/controls/Alert'
import { Segmented } from '@/components/controls/Segmented'
import { Section } from '@/components/controls/Section'
import { Hypnogram } from '@/components/charts/Hypnogram'
import { TimeCurves, type TimeCurveSeries } from '@/components/charts/TimeCurves'
import { Icon } from '@/components/icons/Icon'
import { Headline, TopBar } from '@/components/shell/PageHead'
import { useT } from '@/i18n/useT'
import { longDate, parseIsoDate } from '@/lib/dates'
import { formatNumber, formatSigned, joinKnown } from '@/lib/format'
import { durationText } from '@/lib/units'
import type { components } from '@/api/schema'
import './recovery.css'

type SleepNightView = components['schemas']['SleepNightView']
type CurveGroup = 'pulse' | 'breathing' | 'recovery' | 'movement'

/** Stress and Body Battery are both 0–100 scores: one scale for the two. */
const SCORE_SCALE = [0, 100] as const

export default function SleepNightScreen() {
  const { t, lang } = useT()
  const navigate = useNavigate()
  const params = useParams({ strict: false }) as { date?: string }
  const todayIso = useTodayIso()
  // Paging to the next night keeps the current one on screen until the next is read.
  const selectedDate = useDeferredValue(params.date || todayIso)

  const { data: night } = useSuspenseQuery({
    queryKey: ['recovery', 'sleep', selectedDate],
    queryFn: async (): Promise<SleepNightView> =>
      ok(api.GET('/api/v1/recovery/sleep/{on_date}', { params: { path: { on_date: selectedDate } } })),
  })

  const [activeCurveGroup, setActiveCurveGroup] = useState<CurveGroup>('pulse')

  // The night's breakdown, when the watch reported one.
  const stageMins = useMemo(() => {
    const m = night.stages_minutes
    if (m.deep === undefined && m.light === undefined && m.rem === undefined && m.awake === undefined) return null
    return { deep: m.deep ?? 0, light: m.light ?? 0, rem: m.rem ?? 0, awake: m.awake ?? 0 }
  }, [night.stages_minutes])

  // Start minutes since midnight for the hypnogram; without a recorded bedtime there is no axis.
  const startMinutes = useMemo(() => {
    if (!night.start_time) return null
    const [hh, mm] = night.start_time.split(':').map((s) => parseInt(s, 10))
    return (hh || 0) * 60 + (mm || 0)
  }, [night.start_time])

  // Convert stage series to 5-minute blocks for the hypnogram; no series, no blocks.
  const stagesArray = useMemo(() => {
    if (night.stages_series.length === 0) return []
    const blocks: number[] = []
    const stageMap: Record<string, number> = { awake: 0, rem: 1, light: 2, deep: 3 }
    for (const seg of night.stages_series) {
      const stageCode = stageMap[seg.stage.toLowerCase()] ?? 2
      const blockCount = Math.max(1, Math.round(seg.duration_min / 5))
      for (let i = 0; i < blockCount; i++) blocks.push(stageCode)
    }
    return blocks
  }, [night.stages_series])

  // The night's curves, grouped by what shares a scale; where two do not (bpm and ms), the second
  // one gets the right-hand axis.
  const activeSeries = useMemo<TimeCurveSeries[]>(() => {
    const pts = (list: SleepNightView['heart_rate']) => list.filter((p) => p.ts !== '').map((p) => ({ ts: p.ts, value: p.value }))
    switch (activeCurveGroup) {
      case 'pulse':
        return [
          { key: 'hr', axis: 'left', label: t('app.sleep.curve.heart_rate'), color: 'var(--bad)', points: pts(night.heart_rate) },
          { key: 'hrv', axis: 'right', label: t('app.sleep.curve.hrv'), color: 'var(--violet)', points: pts(night.hrv) },
        ]
      case 'breathing':
        return [
          { key: 'spo2', axis: 'left', label: t('app.sleep.curve.spo2'), color: 'var(--cool)', points: pts(night.spo2) },
          { key: 'resp', axis: 'right', label: t('app.sleep.curve.respiration'), color: 'var(--good)', points: pts(night.respiration) },
        ]
      case 'recovery':
        return [
          { key: 'stress', axis: 'left', label: t('app.sleep.curve.stress'), color: 'var(--bad)', points: pts(night.stress) },
          { key: 'bb', axis: 'left', label: t('app.sleep.curve.body_battery'), color: 'var(--good)', points: pts(night.body_battery) },
        ]
      case 'movement':
        return [{ key: 'move', axis: 'left', label: t('app.sleep.curve.movement'), color: 'var(--violet)', points: pts(night.movement) }]
    }
  }, [night, activeCurveGroup, t])
  const groupHasData = activeSeries.some((s) => s.points.length > 0)

  const fmtHM = (mins: number) => {
    const h = Math.floor(mins / 60)
    const m = mins % 60
    return h > 0 ? t('app.duration.hm', { h, m }) : t('app.duration.min', { m })
  }

  const dateObj = parseIsoDate(night.date)
  const readings = joinKnown([
    night.spo2_min ? t('app.sleep.min_spo2', { spo2: formatNumber(night.spo2_min, lang) }) : null,
    night.bb_change != null ? t('app.sleep.bb_change', { change: formatSigned(night.bb_change, lang, 0) }) : null,
  ])
  const disturbances = joinKnown([
    night.awake_count != null ? t('app.sleep.awakenings', { n: night.awake_count }) : null,
    night.restless_moments != null ? t('app.sleep.restless', { n: night.restless_moments }) : null,
  ])

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
              {night.rhr ? (
                <span className="sub">{t('app.sleep.sleeping_rhr', { rhr: formatNumber(night.rhr, lang, 0) })}</span>
              ) : null}
              {readings !== '' && <span className="sub">{readings}</span>}
              {night.sleep_need_minutes != null && night.sleep_need_minutes > 0 && (
                <span className="sub">{t('app.sleep.need', { duration: durationText(night.sleep_need_minutes, t) })}</span>
              )}
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

      {disturbances !== '' && <p className="night-note">{disturbances}</p>}
      {night.breathing_disrupted && (
        <Alert tone="info" className="night-alert">
          {t('app.sleep.breathing_disrupted')}
        </Alert>
      )}

      {/* Sleep Stages Section */}
      <Section
        title={t('app.sleep.stages_title')}
        meta={night.start_time && night.end_time ? `${night.start_time} → ${night.end_time}` : undefined}
      >
        <div className="panel bare">
          {startMinutes !== null && stagesArray.length > 0 && <Hypnogram stages={stagesArray} startMinutes={startMinutes} />}

          {stageMins !== null && (
            <>
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
            </>
          )}
        </div>
      </Section>

      {/* Overnight Curves Section */}
      <Section title={t('app.sleep.metrics_title')}>
        <div className="panel bare">
          <div className="night-groups">
            <Segmented
              value={activeCurveGroup}
              onChange={setActiveCurveGroup}
              label={t('app.sleep.metrics_label')}
              options={[
                { id: 'pulse', label: t('app.sleep.tab_pulse') },
                { id: 'breathing', label: t('app.sleep.tab_breathing') },
                { id: 'recovery', label: t('app.sleep.tab_recovery') },
                { id: 'movement', label: t('app.sleep.tab_movement') },
              ]}
            />
          </div>

          <div className="night-curves">
            {groupHasData ? (
              <TimeCurves series={activeSeries} leftRange={activeCurveGroup === 'recovery' ? SCORE_SCALE : undefined} label={t('app.sleep.curves_label')} />
            ) : (
              <p className="m">{t('app.sleep.no_curves')}</p>
            )}
          </div>
        </div>
      </Section>
    </>
  )
}
