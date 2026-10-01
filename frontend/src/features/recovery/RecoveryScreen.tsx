import { useMemo } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { api, failText, ok } from '@/api/client'
import { Hypnogram, STAGE_COLOR } from '@/components/charts/Hypnogram'
import { TimeCurves, type TimeCurveSeries } from '@/components/charts/TimeCurves'
import { Alert } from '@/components/controls/Alert'
import { FigureBody, Section } from '@/components/controls/Section'
import { RangeBar } from '@/components/controls/Meters'
import { SectionTabs } from '@/components/controls/SectionTabs'
import { TextButton } from '@/components/controls/Marks'
import { Icon } from '@/components/icons/Icon'
import { toast } from '@/components/controls/toast'
import { hrefOf, useGo } from '@/components/shell/navigation'
import { DomainAlerts } from '@/components/controls/DomainAlerts'
import { Headline, Mast, TopBar } from '@/components/shell/PageHead'
import { preloadScreen } from '@/components/shell/screens'
import { type ScreenId } from '@/components/shell/nav'
import { useToday } from '@/app/session'
import { useT } from '@/i18n/useT'
import { cx } from '@/lib/cx'
import { daysBetween, longDate, parseIsoDate, shortDate, syncedLabel, weekdayShort } from '@/lib/dates'
import { formatCompact, formatCompactNumber, formatInt } from '@/lib/format'
import { durationShort, durationText } from '@/lib/units'
import { isWorse, toneCell } from './tones'
import type { Norm, NormKey } from './types'
import { useRecoveryView } from './useRecoveryView'
import './recovery.css'

const HEAT_ROWS: readonly NormKey[] = ['sleep', 'hrv', 'rhr', 'stress', 'steps', 'bb']
/** Stress and Body Battery are both 0–100 scores: one scale, so a stress spike reads against the drain. */
const DAY_SCALE = [0, 100] as const
const GARMIN_TABS: readonly { id: ScreenId; key: string }[] = [
  { id: 'recovery', key: 'app.garmin.tab.overview' },
  { id: 'nights', key: 'app.garmin.tab.sleep' },
  { id: 'activities', key: 'app.garmin.tab.workouts' },
]

const minutesOf = (hhmm: string): number => {
  const [h = 0, m = 0] = hhmm.split(':').map(Number)
  return h * 60 + m
}

/** A norm's unit code in the user's language ("ms" → "мс"); a dimensionless one is empty. */
const unitName = (unit: string, t: (key: string) => string): string => (unit === 'ms' ? t('app.unit.ms') : unit === 'bpm' ? t('app.unit.bpm') : '')

export default function RecoveryScreen() {
  const { t, lang, plural } = useT()
  const today = useToday()
  const view = useRecoveryView()
  const go = useGo()
  const queryClient = useQueryClient()

  const syncMutation = useMutation({
    mutationFn: () => ok(api.POST('/api/v1/recovery/sync')),
    onSuccess: (result) => {
      if (!result.ok) {
        toast(result.error === 'not_configured' ? t('app.recovery.sync_not_configured') : t('app.recovery.sync_failed'), { icon: 'warn' })
        return
      }
      void queryClient.invalidateQueries({ queryKey: ['recovery'] })
      void queryClient.invalidateQueries({ queryKey: ['today'] })
      // The rail's recovery row.
      void queryClient.invalidateQueries({ queryKey: ['session'] })
      toast(result.synced_days === 0 ? t('app.recovery.sync_none') : t('app.recovery.sync_done'))
    },
    onError: (err) => toast(failText(err, t('app.recovery.sync_failed')), { icon: 'warn' }),
  })

  const { headline: h, night, norms, activity: act } = view
  const curves = useMemo<TimeCurveSeries[]>(
    () => [
      { key: 'stress', axis: 'left', label: t('app.recovery.curve.stress'), color: 'var(--bad)', points: view.intraday.stress },
      { key: 'bb', axis: 'left', label: t('app.recovery.curve.body_battery'), color: 'var(--good)', points: view.intraday.bodyBattery },
      { key: 'hr', axis: 'right', label: t('app.recovery.curve.heart_rate'), color: 'var(--violet)', points: view.intraday.heartRate },
    ],
    [view.intraday, t],
  )
  const hasCurves = curves.some((c) => c.points.length > 0)
  const shownDay = shortDate(parseIsoDate(view.dateIso), lang)
  // Garmin counts a vigorous minute as two toward the weekly goal: the watch shows the weighted sum.
  const intensity =
    act.intensityModerate === null && act.intensityVigorous === null ? null : (act.intensityModerate ?? 0) + 2 * (act.intensityVigorous ?? 0)
  const dayMeta = [
    view.isToday ? null : t('app.recovery.day_of', { date: shownDay }),
    view.lastSync === null ? t('app.recovery.never_synced') : t('app.recovery.synced', { when: syncedLabel(view.lastSync, today, lang) }),
  ]
    .filter((x) => x !== null)
    .join(' · ')
  const dash = '—'
  const num = (v: number | null) => (v === null ? dash : formatCompact(v, lang))
  const cellText = (key: NormKey, value: number | null) => (value === null ? dash : key === 'steps' ? formatCompactNumber(value, lang) : formatCompact(value, lang))
  const rangeText = (norm: Norm) => `${formatInt(norm.lo, lang)}–${formatInt(norm.hi, lang)}`
  const relative = (iso: string) => {
    const k = daysBetween(parseIsoDate(iso), today)
    return k === 0 ? t('app.today_word_lower') : k === 1 ? t('app.yesterday_word_lower') : weekdayShort(parseIsoDate(iso), lang)
  }

  return (
    <>
      <TopBar
        title={t('nav.garmin')}
        right={
          view.isConfigured ? (
            <button
              type="button"
              className={cx('ibtn', syncMutation.isPending && 'spin')}
              onClick={() => !syncMutation.isPending && syncMutation.mutate()}
              aria-label={t('app.sync')}
            >
              <Icon name="sync" />
            </button>
          ) : undefined
        }
      />
      <Mast
        screen="recovery"
        actions={
          view.isConfigured ? (
            <TextButton icon="sync" spinning={syncMutation.isPending} onClick={() => !syncMutation.isPending && syncMutation.mutate()}>
              {t('app.sync')}
            </TextButton>
          ) : undefined
        }
        sub={
          <SectionTabs
            sub
            items={GARMIN_TABS.map((tab) => ({ id: tab.id, label: t(tab.key), href: hrefOf(tab.id) }))}
            active="recovery"
            onSelect={(id) => go(id as ScreenId, { mode: 'replace' })}
            onPreload={(id) => void preloadScreen(id as ScreenId)}
          />
        }
      />
      <Headline title={t('nav.garmin')}>
        <div className="figs inline">
          <div className="f">
            <FigureBody value={num(h.sleepScore)} label={t('today.metric_sleep_score')} sub={h.sleepMinutes === null ? undefined : durationText(h.sleepMinutes, t)} />
          </div>
          <div className="f">
            <FigureBody
              value={num(h.hrv)}
              unit={h.hrv === null ? undefined : t('app.unit.ms')}
              label={t('today.metric_hrv_avg')}
              sub={
                h.hrvNightsBelow === 0
                  ? undefined
                  : plural(h.hrvNightsBelow, t('app.recovery.below.one', { n: h.hrvNightsBelow }), t('app.recovery.below.few', { n: h.hrvNightsBelow }), t('app.recovery.below.many', { n: h.hrvNightsBelow }))
              }
              tone={isWorse(h.hrv, norms.hrv) ? 'bad' : undefined}
            />
          </div>
          <div className="f">
            <FigureBody value={num(h.rhr)} unit={h.rhr === null ? undefined : t('app.unit.bpm')} label={t('app.metric.rhr')} sub={h.rhrNote === '' ? undefined : t(`app.recovery.rhr_note.${h.rhrNote}`)} />
          </div>
          <div className="f">
            <FigureBody
              value={h.bodyBatteryFrom === null || h.bodyBatteryTo === null ? dash : `${h.bodyBatteryFrom}→${h.bodyBatteryTo}`}
              label={t('today.metric_body_battery_high')}
              sub={h.bodyBatteryFrom === null || h.bodyBatteryTo === null ? undefined : t('app.recovery.bb_charge')}
            />
          </div>
        </div>
      </Headline>
      <DomainAlerts domain="garmin" scope="recovery" />
      {view.advice !== null && (
        <Alert tone="note" className="rec-advice" evidence={t('app.recovery.observation')}>
          {view.advice}
        </Alert>
      )}

      <Section title={t('app.recovery.day_title')} meta={dayMeta}>
        <div className="figs">
          <div className="f">
            <FigureBody value={act.steps === null ? dash : formatInt(act.steps, lang)} label={t('app.metric.steps')} />
          </div>
          <div className="f">
            <FigureBody value={num(act.stress)} label={t('app.recovery.stress_avg')} />
          </div>
          <div className="f">
            <FigureBody
              value={intensity === null ? dash : formatInt(intensity, lang)}
              label={t('app.recovery.intensity')}
              sub={act.intensityVigorous ? t('app.recovery.intensity_breakdown', { mod: act.intensityModerate ?? 0, vig: act.intensityVigorous }) : undefined}
            />
          </div>
          <div className="f">
            <FigureBody
              value={act.activeCalories === null ? dash : formatInt(act.activeCalories, lang)}
              unit={act.activeCalories === null ? undefined : t('app.unit.kcal')}
              label={t('app.recovery.active_cal')}
            />
          </div>
        </div>
      </Section>

      {hasCurves && (
        <Section title={t('app.recovery.intraday_title')} meta={shownDay}>
          <div className="panel bare">
            <TimeCurves series={curves} leftRange={DAY_SCALE} label={t('app.recovery.intraday_label')} />
          </div>
        </Section>
      )}

      <div className="grid recovery-grid">
        {night !== null && (
          <div className="c7">
            <Section
              title={t('app.recovery.night_of', { date: longDate(parseIsoDate(night.dateIso), lang) })}
              meta={night.start !== null && night.end !== null ? <span className="meta num">{`${night.start} → ${night.end}`}</span> : undefined}
            >
              <div className="panel bare">
                {night.start !== null && night.stages.length > 0 && <Hypnogram stages={night.stages} startMinutes={minutesOf(night.start)} />}
                {night.stageMinutes !== null && (
                  <>
                    <div className="compo intro">
                      <i style={{ flex: night.stageMinutes[3], background: STAGE_COLOR[3] }} />
                      <i style={{ flex: night.stageMinutes[2], background: STAGE_COLOR[2] }} />
                      <i style={{ flex: night.stageMinutes[1], background: STAGE_COLOR[1] }} />
                      <i style={{ flex: night.stageMinutes[0], background: STAGE_COLOR[0] }} />
                    </div>
                    <div className="hyp-legend">
                      <div>
                        <i style={{ background: STAGE_COLOR[3] }} />
                        {t('app.stage.deep')}
                        <b>{durationShort(night.stageMinutes[3], t)}</b>
                      </div>
                      <div>
                        <i style={{ background: STAGE_COLOR[2] }} />
                        {t('app.stage.light')}
                        <b>{durationShort(night.stageMinutes[2], t)}</b>
                      </div>
                      <div>
                        <i style={{ background: STAGE_COLOR[1] }} />
                        {t('app.stage.rem')}
                        <b>{durationShort(night.stageMinutes[1], t)}</b>
                      </div>
                      <div>
                        <i style={{ background: STAGE_COLOR[0] }} />
                        {t('app.stage.awake')}
                        <b>{t('app.duration.min', { m: night.stageMinutes[0] })}</b>
                      </div>
                    </div>
                  </>
                )}
              </div>
            </Section>
          </div>
        )}

        <div className="c5">
          <Section
            title={t('app.recovery.norms_title')}
            meta={view.normsDays > 0 ? t('app.recovery.norms_meta', { days: view.normsDays }) : t('app.recovery.norms_pending', { days: view.normsMinDays })}
          >
            <div className="rows norms">
              {view.bars.map((bar) => {
                const norm = norms[bar.key]
                const bad = isWorse(bar.value, norm)
                const unitLabel = unitName(bar.unit, t)
                return (
                  <div key={bar.key} className="row">
                    <div>
                      <div className="t">{t(`app.metric.${bar.key}`)}</div>
                      {norm !== undefined && (
                        <div className="m">
                          {t('app.recovery.norm', { range: rangeText(norm) })}
                          {unitLabel !== '' && ` ${unitLabel}`}
                        </div>
                      )}
                    </div>
                    <div className={cx('v', bad && 'bad')}>
                      {num(bar.value)}
                      {bar.value !== null && unitLabel !== '' && <span className="u">{unitLabel}</span>}
                    </div>
                    {bar.value !== null && norm !== undefined && <RangeBar value={bar.value} lo={norm.lo} hi={norm.hi} min={bar.min} max={bar.max} tone={bad ? 'bad' : ''} />}
                  </div>
                )
              })}
            </div>
          </Section>
        </div>
      </div>

      <Section title={t('app.recovery.days_title', { n: view.days.length })} meta={t('app.recovery.days_meta')}>
        <div className="heat">
          <table>
            <colgroup>
              <col className="lblc" />
              {view.days.map((d) => (
                <col key={d.dateIso} />
              ))}
            </colgroup>
            <thead>
              <tr>
                <th />
                {view.days.map((d, i) => {
                  const date = parseIsoDate(d.dateIso)
                  return (
                    <th key={d.dateIso} className={i === view.days.length - 1 ? 'now' : undefined}>
                      {weekdayShort(date, lang)}
                      <br />
                      {date.getDate()}
                    </th>
                  )
                })}
              </tr>
            </thead>
            <tbody>
              {HEAT_ROWS.map((key) => (
                <tr key={key}>
                  <td className="lbl">
                    {t(`app.metric.${key}`)}
                    {norms[key] !== undefined && <small>{rangeText(norms[key])}</small>}
                  </td>
                  {view.days.map((d) => (
                    <td key={d.dateIso}>
                      <div className={cx('cell', toneCell(d[key], norms[key]))}>{cellText(key, d[key])}</div>
                    </td>
                  ))}
                </tr>
              ))}
              <tr>
                <td className="lbl">{t('app.metric.awake')}</td>
                {view.days.map((d) => (
                  <td key={d.dateIso}>
                    <div className="cell">{d.awake === null ? dash : formatInt(d.awake, lang)}</div>
                  </td>
                ))}
              </tr>
            </tbody>
          </table>
        </div>

        <div className="days-m">
          <div className="days-head">
            <span>{t('app.recovery.col_day')}</span>
            <span>{t('app.recovery.col_sleep')}</span>
            <span>{t('app.recovery.col_hrv')}</span>
            <span>{t('app.recovery.col_rhr')}</span>
            <span>{t('app.recovery.col_steps')}</span>
            <span>{t('app.recovery.col_awake')}</span>
          </div>
          <div className="days">
            {[...view.days]
              .reverse()
              .slice(0, 10)
              .map((d) => (
                <div key={d.dateIso} className="day">
                  <div className="d">
                    {relative(d.dateIso)}
                    <small>{shortDate(parseIsoDate(d.dateIso), lang)}</small>
                  </div>
                  {(['sleep', 'hrv', 'rhr', 'steps'] as const).map((key) => (
                    <div key={key} className={cx('cell', toneCell(d[key], norms[key]))}>
                      {cellText(key, d[key])}
                    </div>
                  ))}
                  <div className="cell">{d.awake === null ? dash : formatInt(d.awake, lang)}</div>
                </div>
              ))}
          </div>
        </div>
      </Section>
    </>
  )
}
