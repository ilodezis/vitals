import { useState } from 'react'
import { Hypnogram, STAGE_COLOR } from '@/components/charts/Hypnogram'
import { FigureBody, Section } from '@/components/controls/Section'
import { RangeBar } from '@/components/controls/Meters'
import { SectionTabs } from '@/components/controls/SectionTabs'
import { TextButton } from '@/components/controls/Marks'
import { toast } from '@/components/controls/toast'
import { hrefOf, useGo } from '@/components/shell/navigation'
import { Headline, Mast, TopBar } from '@/components/shell/PageHead'
import { preloadScreen } from '@/components/shell/screens'
import { type ScreenId } from '@/components/shell/nav'
import { FIXTURE_TODAY } from '@/fixtures/series'
import { useT } from '@/i18n/useT'
import { cx } from '@/lib/cx'
import { daysBetween, longDate, parseIsoDate, shortDate, weekdayShort } from '@/lib/dates'
import { formatInt, formatNumber } from '@/lib/format'
import { wait } from '@/lib/motion'
import { durationShort, durationText } from '@/lib/units'
import { isWorse, toneCell } from './tones'
import type { NormKey } from './types'
import { useRecoveryView } from './useRecoveryView'
import './recovery.css'

const HEAT_ROWS: readonly NormKey[] = ['sleep', 'hrv', 'rhr', 'stress', 'steps', 'bb']
const GARMIN_TABS: readonly { id: ScreenId; key: string }[] = [
  { id: 'recovery', key: 'app.garmin.tab.overview' },
  { id: 'nights', key: 'app.garmin.tab.sleep' },
  { id: 'activities', key: 'app.garmin.tab.workouts' },
]

const minutesOf = (hhmm: string): number => {
  const [h = 0, m = 0] = hhmm.split(':').map(Number)
  return h * 60 + m
}

export default function RecoveryScreen() {
  const { t, lang, plural } = useT()
  const view = useRecoveryView()
  const go = useGo()
  const [syncing, setSyncing] = useState(false)

  const { headline: h, night, norms } = view
  const [awake, rem, light, deep] = night.stageMinutes
  const last = view.days[view.days.length - 1]
  const cellText = (key: NormKey, value: number) => (key === 'steps' ? `${formatNumber(value / 1000, lang)}k` : String(value))

  const sync = async () => {
    if (syncing) return
    setSyncing(true)
    await wait(1400)
    setSyncing(false)
    toast(t('app.recovery.sync_none', { time: '08:14' }))
  }

  const rangeText = (key: NormKey) => {
    const n = norms[key]
    return `${formatInt(n.lo, lang)}–${formatInt(n.hi, lang)}`
  }
  const relative = (iso: string) => {
    const k = daysBetween(parseIsoDate(iso), FIXTURE_TODAY)
    return k === 0 ? t('app.today_word_lower') : k === 1 ? t('app.yesterday_word_lower') : weekdayShort(parseIsoDate(iso), lang)
  }

  return (
    <>
      <TopBar title={t('nav.garmin')} />
      <Mast
        screen="recovery"
        actions={
          <TextButton icon="sync" spinning={syncing} onClick={sync}>
            {t('app.sync')}
          </TextButton>
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
            <FigureBody value={h.sleepScore} label={t('today.metric_sleep_score')} sub={durationText(h.sleepMinutes, t)} />
          </div>
          <div className="f">
            <FigureBody
              value={h.hrv}
              unit={t('app.unit.ms')}
              label={t('today.metric_hrv_avg')}
              sub={plural(h.hrvNightsBelow, t('app.recovery.below.one', { n: h.hrvNightsBelow }), t('app.recovery.below.few', { n: h.hrvNightsBelow }), t('app.recovery.below.many', { n: h.hrvNightsBelow }))}
              tone={isWorse(h.hrv, norms.hrv) ? 'bad' : undefined}
            />
          </div>
          <div className="f">
            <FigureBody value={h.rhr} unit={t('app.unit.bpm')} label={t('app.metric.rhr')} sub={h.rhrNote} />
          </div>
          <div className="f">
            <FigureBody value={`${h.bodyBatteryFrom}→${h.bodyBatteryTo}`} label={t('today.metric_body_battery_high')} sub={t('app.recovery.bb_charge')} />
          </div>
        </div>
      </Headline>

      <div className="grid recovery-grid">
        <div className="c7">
          <Section
            title={t('app.recovery.night_of', { date: longDate(parseIsoDate(night.dateIso), lang) })}
            meta={<span className="meta num">{`${night.start} → ${night.end}`}</span>}
          >
            <div className="panel bare">
              <Hypnogram stages={night.stages} startMinutes={minutesOf(night.start)} />
              <div className="compo intro">
                <i style={{ flex: deep, background: STAGE_COLOR[3] }} />
                <i style={{ flex: light, background: STAGE_COLOR[2] }} />
                <i style={{ flex: rem, background: STAGE_COLOR[1] }} />
                <i style={{ flex: awake, background: STAGE_COLOR[0] }} />
              </div>
              <div className="hyp-legend">
                <div>
                  <i style={{ background: STAGE_COLOR[3] }} />
                  {t('app.stage.deep')}
                  <b>{durationShort(deep, t)}</b>
                </div>
                <div>
                  <i style={{ background: STAGE_COLOR[2] }} />
                  {t('app.stage.light')}
                  <b>{durationShort(light, t)}</b>
                </div>
                <div>
                  <i style={{ background: STAGE_COLOR[1] }} />
                  {t('app.stage.rem')}
                  <b>{durationShort(rem, t)}</b>
                </div>
                <div>
                  <i style={{ background: STAGE_COLOR[0] }} />
                  {t('app.stage.awake')}
                  <b>{t('app.duration.min', { m: awake })}</b>
                </div>
              </div>
            </div>
          </Section>
        </div>

        <div className="c5">
          <Section title={t('app.recovery.norms_title')} meta={t('app.recovery.norms_meta')}>
            <div className="rows norms">
              {view.bars.map((bar) => {
                const norm = norms[bar.key]
                const value = last === undefined ? 0 : last[bar.key]
                const bad = isWorse(value, norm)
                return (
                  <div key={bar.key} className="row">
                    <div>
                      <div className="t">{t(`app.metric.${bar.key}`)}</div>
                      <div className="m">
                        {t('app.recovery.norm', { range: rangeText(bar.key) })}
                        {norm.unit !== '' && ` ${norm.unit}`}
                      </div>
                    </div>
                    <div className={cx('v', bad && 'bad')}>
                      {value}
                      {norm.unit !== '' && <span className="u">{norm.unit}</span>}
                    </div>
                    <RangeBar value={value} lo={norm.lo} hi={norm.hi} min={bar.min} max={bar.max} tone={bad ? 'bad' : ''} />
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
                    <small>
                      {formatInt(norms[key].lo, lang)}–{formatInt(norms[key].hi, lang)}
                    </small>
                  </td>
                  {view.days.map((d) => (
                    <td key={d.dateIso}>
                      <div className={cx('cell', toneCell(d[key], norms[key]))}>{cellText(key, d[key])}</div>
                    </td>
                  ))}
                </tr>
              ))}
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
                </div>
              ))}
          </div>
        </div>
      </Section>
    </>
  )
}
