import { Fragment, useEffect, useState } from 'react'
import { Alert } from '@/components/controls/Alert'
import { Dot, Delta } from '@/components/controls/Marks'
import { Meter, RangeBar } from '@/components/controls/Meters'
import { Odometer } from '@/components/controls/Odometer'
import { RichTextView } from '@/components/controls/richText'
import { Section, FigureBody } from '@/components/controls/Section'
import { changeTone } from '@/components/controls/gauges'
import { Icon } from '@/components/icons/Icon'
import { openLogSheet } from '@/components/sheet/logSheetStore'
import { ScreenLink } from '@/components/shell/navigation'
import { TopBar } from '@/components/shell/PageHead'
import { useScreen } from '@/components/shell/ScreenFrame'
import { WeightForm } from '@/features/weight/WeightForm'
import { useLoggedWeight } from '@/features/weight/weightLog'
import { useT } from '@/i18n/useT'
import { cx } from '@/lib/cx'
import { fullDate, longDate, parseIsoDate, syncedLabel } from '@/lib/dates'
import { formatInt, formatNumber, formatSigned } from '@/lib/format'
import { prefersReducedMotion } from '@/lib/motion'
import { durationText } from '@/lib/units'
import { FIXTURE_TODAY } from '@/fixtures/series'
import { useTodayView } from './useTodayView'
import './today.css'

/** The words of a sentence, one by one, for the entrance: each fades up out of a blur a little
 *  after the one before. */
function Words({ text, from, step }: { text: string; from: number; step: number }) {
  return (
    <>
      {text.split(' ').map((word, i) => (
        <Fragment key={i}>
          <span className="w" style={{ animationDelay: `${60 + (from + i) * step}ms` }}>
            {word}
          </span>{' '}
        </Fragment>
      ))}
    </>
  )
}

const FIGURES = 5
const ROLL_START_MS = 420
const ROLL_GAP_MS = 70

/** Which of the five figures have arrived. On the first visit they wait for the sentence, then
 *  come one after another; later they are simply there. */
function useArrival(enabled: boolean): { arrived: boolean[]; staggering: boolean } {
  const [arrived, setArrived] = useState<boolean[]>(() => Array<boolean>(FIGURES).fill(!enabled))
  const [staggering, setStaggering] = useState(enabled)
  useEffect(() => {
    if (!enabled) return
    const reduced = prefersReducedMotion()
    const timers = Array.from({ length: FIGURES }, (_, i) =>
      window.setTimeout(() => setArrived((prev) => prev.map((v, k) => (k === i ? true : v))), reduced ? 0 : ROLL_START_MS + i * ROLL_GAP_MS),
    )
    timers.push(window.setTimeout(() => setStaggering(false), reduced ? 0 : ROLL_START_MS + FIGURES * ROLL_GAP_MS + 1600))
    return () => timers.forEach((id) => window.clearTimeout(id))
  }, [enabled])
  return { arrived, staggering }
}

export default function TodayScreen() {
  const { t, lang, plural } = useT()
  const view = useTodayView()
  const { firstVisit } = useScreen()
  const logged = useLoggedWeight()
  const [intro] = useState(firstVisit)
  const { arrived, staggering } = useArrival(intro)
  const stagger = staggering ? 40 : 0

  const today = parseIsoDate(view.dateIso)
  const weight = logged.kg
  const done = view.goal.startKg - weight
  const total = view.goal.startKg - view.goal.targetKg
  const progress = (done / total) * 100
  const feedCount = view.feed.length + logged.added.length
  const weekDelta = view.weight.weekDeltaKg
  const leadWords = view.narrative.lead.split(' ').length

  const chevron = <Icon name="chevR" className="go" />

  return (
    <>
      <TopBar title={t('nav.today')} />
      <div className="today-top">
        <div className="kicker">
          {fullDate(today, lang)} <span className="sep" /> <span className="num">{view.now}</span>
        </div>
        <div className="sync">
          {view.sync.map((s) => (
            <span key={s.source}>
              <Dot tone={s.ok ? 'good' : 'bad'} />
              {s.source} · {syncedLabel(s.at, FIXTURE_TODAY, lang)}
            </span>
          ))}
        </div>
      </div>

      <h1 className={cx('narr', intro && 'intro')}>
        {intro ? <Words text={view.narrative.lead} from={0} step={26} /> : view.narrative.lead}{' '}
        <em>{intro ? <Words text={view.narrative.note} from={leadWords} step={26} /> : view.narrative.note}</em>
      </h1>

      <div className="figs today-figs">
        <ScreenLink screen="weight" sharedFigure className="f f-weight">
          <div className="fig-weight">
            <div className="fw-v" data-fig="weight">
              <Odometer value={formatNumber(weight, lang)} hidden={!arrived[0]} stagger={stagger} />
              <span className="u">{t('app.unit.kg')}</span>
            </div>
          </div>
          <div className="f-l">
            {t('today.metric_weight')}{' '}
            <Delta tone={weekDelta <= 0 ? 'good' : undefined} icon={weekDelta <= 0 ? 'down' : 'up'} className="today-delta">
              {t('today.trend_week', { value: formatNumber(Math.abs(weekDelta), lang) })}
            </Delta>
          </div>
          {chevron}
        </ScreenLink>
        <ScreenLink screen="recovery" className="f">
          <FigureBody
            value={<Odometer value={String(view.sleep.score)} hidden={!arrived[1]} stagger={stagger} />}
            label={t('today.metric_sleep_score')}
            sub={durationText(view.sleep.minutes, t)}
          />
          {chevron}
        </ScreenLink>
        <ScreenLink screen="recovery" className="f">
          <FigureBody
            value={<Odometer value={String(view.hrv.ms)} hidden={!arrived[2]} stagger={stagger} />}
            unit={t('app.unit.ms')}
            label={t('today.metric_hrv_avg')}
            sub={view.hrv.ms < view.hrv.lo ? t('app.today.below_norm', { lo: view.hrv.lo, hi: view.hrv.hi }) : t('app.today.in_norm')}
            tone={view.hrv.ms < view.hrv.lo ? 'bad' : undefined}
          />
          {chevron}
        </ScreenLink>
        <ScreenLink screen="recovery" className="f">
          <FigureBody
            value={<Odometer value={String(view.bodyBattery.value)} hidden={!arrived[3]} stagger={stagger} />}
            label={t('today.metric_body_battery_high')}
            sub={t('app.today.bb_gained', { value: formatSigned(view.bodyBattery.gained, lang, 0) })}
          />
          {chevron}
        </ScreenLink>
        <ScreenLink screen="nutrition" className="f">
          <FigureBody
            value={<Odometer value={String(view.intake.kcal)} hidden={!arrived[4]} stagger={stagger} />}
            unit={t('app.unit.kcal')}
            label={t('today.metric_calories')}
            sub={t('app.today.of_target', { value: formatInt(view.intake.target, lang) })}
          />
          {chevron}
        </ScreenLink>
      </div>

      <div className="grid">
        <div className="c7">
          <Section className="o2" title={t('app.today.week_title')} meta={t('app.today.week_meta')}>
            <div className="rows">
              {view.weekChanges.map((c) => {
                const tone = changeTone(c.from, c.to, c.better)
                return (
                  <ScreenLink key={c.metric} screen={c.screen} className="row dumb">
                    <div>
                      <div className="t">{t(`app.metric.${c.metric}`)}</div>
                      <div className="m num">
                        {formatNumber(c.from, lang)} → {formatNumber(c.to, lang)}
                        {c.unit !== '' && ` ${c.unit}`}
                      </div>
                    </div>
                    <RangeBar value={c.to} prev={c.from} lo={c.lo} hi={c.hi} min={c.min} max={c.max} tone={tone} />
                    <div className={cx('v', tone)}>{formatSigned(c.to - c.from, lang)}</div>
                  </ScreenLink>
                )
              })}
            </div>
          </Section>
          <Section
            className="o3"
            title={t('app.today.day_title')}
            meta={plural(feedCount, t('app.today.entries.one', { n: feedCount }), t('app.today.entries.few', { n: feedCount }), t('app.today.entries.many', { n: feedCount }))}
          >
            <div className="feed">
              {view.feed.map((f) => (
                <div key={f.time + f.text} className="feed-row">
                  <span className="time">{f.time}</span>
                  <span className="rail-dot">
                    <Dot tone={f.tone} />
                  </span>
                  <div>
                    <div className="tx">{f.text}</div>
                    <div className="dt">{f.detail}</div>
                  </div>
                </div>
              ))}
              {logged.added.map((a) => (
                <div key={a.id} className="feed-row enter">
                  <span className="time">{a.at}</span>
                  <span className="rail-dot">
                    <Dot tone="good" />
                  </span>
                  <div>
                    <div className="tx">{t('app.feed.weight', { value: formatNumber(a.kg, lang) })}</div>
                    <div className="dt">{t('app.source.manual')}</div>
                  </div>
                </div>
              ))}
            </div>
          </Section>
        </div>

        <div className="c5">
          <div className="panel today-log sec o0">
            <div className="panel-h">
              <h3>{t('app.today.weight_today')}</h3>
              <span className="sub">{t('app.today.weight_morning', { value: formatNumber(weight, lang), time: view.weight.measuredAt })}</span>
            </div>
            <WeightForm />
            <div className="qchips">
              <button type="button" className="qchip" onClick={() => openLogSheet('meal')}>
                <Icon name="bowl" />
                {t('app.log.tab.meal')}
              </button>
              <button type="button" className="qchip" onClick={() => openLogSheet('dose')}>
                <Icon name="syringe" />
                {t('app.log.tab.dose')}
              </button>
              <button type="button" className="qchip" onClick={() => openLogSheet('measure')}>
                <Icon name="ruler" />
                {t('app.log.tab.measure')}
              </button>
            </div>
          </div>

          <Section className="o1" title={t('app.today.attention_title')} meta={String(view.attention.length)}>
            <div className="alerts">
              {view.attention.map((item, i) => {
                const body = (
                  <>
                    {item.lead !== undefined && <span style={{ color: 'var(--muted)' }}>{item.lead}</span>}
                    <RichTextView parts={item.parts} />
                  </>
                )
                return item.screen === undefined ? (
                  <Alert key={i} tone={item.tone} icon={item.tone === 'info' ? 'cal' : undefined} evidence={item.evidence}>
                    {body}
                  </Alert>
                ) : (
                  <Alert key={i} as={ScreenLink} screen={item.screen} tone={item.tone} evidence={item.evidence}>
                    {body}
                  </Alert>
                )
              })}
            </div>
          </Section>

          <Section
            className="o4"
            title={t('app.today.goal_title')}
            meta={t('app.today.goal_meta', { kg: formatNumber(view.goal.targetKg, lang, 0), date: longDate(parseIsoDate(view.goal.deadlineIso), lang) })}
          >
            <div className="goal-top">
              <span className="gv">
                {formatNumber(done, lang)}
                <span className="u">{t('app.today.goal_of', { total: formatNumber(total, lang, 0) })}</span>
              </span>
              <span className="sub num">{Math.round(progress)} %</span>
            </div>
            <Meter value={progress} ticks={[25, 50, 75]} />
            <div className="goal-scale">
              <span>{formatNumber(view.goal.startKg, lang, 0)}</span>
              <span>{t('app.now_value', { value: formatNumber(weight, lang) })}</span>
              <span>{formatNumber(view.goal.targetKg, lang, 0)}</span>
            </div>
            <p className="sub goal-forecast">{view.goal.forecast}</p>
          </Section>
        </div>
      </div>
    </>
  )
}
