import { Fragment, useEffect, useState, type CSSProperties } from 'react'
import { useSession } from '@/app/session'
import { Alert } from '@/components/controls/Alert'
import { Dot, Delta } from '@/components/controls/Marks'
import { Meter, RangeBar } from '@/components/controls/Meters'
import { Odometer } from '@/components/controls/Odometer'
import { Section, FigureBody } from '@/components/controls/Section'
import { rangeAxis } from '@/components/controls/gauges'
import { Icon } from '@/components/icons/Icon'
import { openLogSheet } from '@/components/sheet/logSheetStore'
import { MODULE_SCREEN } from '@/components/shell/nav'
import { ScreenLink } from '@/components/shell/navigation'
import { TopBar } from '@/components/shell/PageHead'
import { useScreen } from '@/components/shell/ScreenFrame'
import { WeightForm } from '@/features/weight/WeightForm'
import { useLastWeighed } from '@/features/weight/useLastWeighed'
import { useT } from '@/i18n/useT'
import { cx } from '@/lib/cx'
import { fullDate, longDate, parseIsoDate, relativeDay } from '@/lib/dates'
import { formatCompact, formatInt, formatNumber, formatPercent, formatSigned } from '@/lib/format'
import { prefersReducedMotion } from '@/lib/motion'
import { durationText } from '@/lib/units'
import { useClock } from '@/lib/useClock'
import { corridorStatus, forecastPhrase, goalProgress, splitNarrative } from './derive'
import { feedLine } from './feedLine'
import type { TodayFigure, TodayView, WeekChange } from './types'
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

/** The order the figures arrive in on the first visit. A figure the day does not have (a module
 *  that is off) leaves its slot empty. */
const FIGURE_ORDER = ['weight', 'sleep_score', 'hrv_avg', 'body_battery_high', 'calories'] as const
const ROLL_START_MS = 420
const ROLL_GAP_MS = 70

/** Which of the figures have arrived. On the first visit they wait for the sentence, then come one
 *  after another; later they are simply there. */
function useArrival(enabled: boolean): { arrived: boolean[]; staggering: boolean } {
  const [arrived, setArrived] = useState<boolean[]>(() => Array<boolean>(FIGURE_ORDER.length).fill(!enabled))
  const [staggering, setStaggering] = useState(enabled)
  useEffect(() => {
    if (!enabled) return
    const reduced = prefersReducedMotion()
    const timers = Array.from({ length: FIGURE_ORDER.length }, (_, i) =>
      window.setTimeout(() => setArrived((prev) => prev.map((v, k) => (k === i ? true : v))), reduced ? 0 : ROLL_START_MS + i * ROLL_GAP_MS),
    )
    timers.push(window.setTimeout(() => setStaggering(false), reduced ? 0 : ROLL_START_MS + FIGURE_ORDER.length * ROLL_GAP_MS + 1600))
    return () => timers.forEach((id) => window.clearTimeout(id))
  }, [enabled])
  return { arrived, staggering }
}

/** The clock in the kicker; it alone re-renders on the minute. */
function Clock() {
  return <span className="num">{useClock()}</span>
}

/** What each week-over-week row measures in, and how many decimals its numbers carry. */
const CHANGE_UNIT: Partial<Record<WeekChange['key'], string>> = {
  weight: 'app.unit.kg',
  hrv_avg: 'app.unit.ms',
  calories: 'app.unit.kcal',
}
const CHANGE_DIGITS: Partial<Record<WeekChange['key'], number>> = { calories: 0 }

const figureOf = (view: TodayView, key: TodayFigure['key']): TodayFigure | undefined => view.figures.find((f) => f.key === key)

/** A figure that has no reading yet stays where it is, as a dash. */
function Reading({ value, format, hidden, stagger }: { value: number | null; format: (n: number) => string; hidden: boolean; stagger: number }) {
  return value === null ? <span>—</span> : <Odometer value={format(value)} hidden={hidden} stagger={stagger} />
}

export default function TodayScreen() {
  const { t, lang, plural } = useT()
  const view = useTodayView()
  const { enabled_modules: modules } = useSession()
  const { firstVisit } = useScreen()
  const lastWeighed = useLastWeighed()
  const [intro] = useState(firstVisit)
  const { arrived, staggering } = useArrival(intro)
  const stagger = staggering ? 40 : 0
  // Only a weigh-in that was not there when the screen opened plays the entrance.
  const [hadWeighIn] = useState(() => view.feed.some((row) => row.kind === 'weight'))
  const [expandedAttention, setExpandedAttention] = useState(false)

  const today = parseIsoDate(view.date)
  const labels = { today: t('app.today_word'), yesterday: t('app.yesterday_word') }
  const { lead, note } = splitNarrative(view.narrative)
  const leadWords = lead.split(' ').length

  const weight = figureOf(view, 'weight')
  const sleep = figureOf(view, 'sleep_score')
  const hrv = figureOf(view, 'hrv_avg')
  const battery = figureOf(view, 'body_battery_high')
  const calories = figureOf(view, 'calories')
  const trend = weight?.trend ?? null
  const flat = trend === null || Math.abs(trend) < 0.05
  const hrvStatus = corridorStatus(hrv?.value ?? null, hrv?.corridor ?? null)
  const arrival = (key: TodayFigure['key']) => arrived[FIGURE_ORDER.indexOf(key)] ?? true
  const shown = view.figures.length

  const chevron = <Icon name="chevR" className="go" />
  const entries = view.feed.length

  return (
    <>
      <TopBar title={t('nav.today')} />
      <div className="today-top">
        <div className="kicker">
          {fullDate(today, lang)} <span className="sep" /> <Clock />
        </div>
        <div className="sync">
          {view.sync.length === 0 ? (
            <span>{t('today.sync_none')}</span>
          ) : (
            view.sync.map((s) => (
              <span key={s.source}>
                <Dot tone="good" />
                {s.source} · {relativeDay(parseIsoDate(s.date), today, lang, labels)}
              </span>
            ))
          )}
        </div>
      </div>

      <h1 className={cx('narr', intro && 'intro', view.narrative.length > 140 && 'is-long')}>
        {intro ? <Words text={lead} from={0} step={26} /> : lead}
        {note !== '' && (
          <>
            {' '}
            <em>{intro ? <Words text={note} from={leadWords} step={26} /> : note}</em>
          </>
        )}
      </h1>

      <div className="figs today-figs" style={{ '--figs': Math.max(shown - 1, 1) } as CSSProperties}>
        {weight !== undefined && (
          <ScreenLink screen="weight" sharedFigure className="f f-weight">
            <div className="fig-weight">
              <div className="fw-v" data-fig="weight">
                <Reading value={weight.value} format={(n) => formatNumber(n, lang)} hidden={!arrival('weight')} stagger={stagger} />
                <span className="u">{t('app.unit.kg')}</span>
              </div>
            </div>
            <div className="f-l">
              {t('today.metric_weight')}
              {trend !== null && (
                <>
                  {' '}
                  <Delta tone={trend < 0 && !flat ? 'good' : undefined} icon={flat ? undefined : trend < 0 ? 'down' : 'up'} className="today-delta">
                    {t('today.trend_week', { value: formatNumber(Math.abs(trend), lang) })}
                  </Delta>
                </>
              )}
            </div>
            {chevron}
          </ScreenLink>
        )}
        {sleep !== undefined && (
          <ScreenLink screen="recovery" className="f">
            <FigureBody
              value={<Reading value={sleep.value} format={(n) => formatInt(n, lang)} hidden={!arrival('sleep_score')} stagger={stagger} />}
              label={t('today.metric_sleep_score')}
              sub={sleep.sleep_seconds === null ? undefined : durationText(sleep.sleep_seconds / 60, t)}
            />
            {chevron}
          </ScreenLink>
        )}
        {hrv !== undefined && (
          <ScreenLink screen="recovery" className="f">
            <FigureBody
              value={<Reading value={hrv.value} format={(n) => formatInt(n, lang)} hidden={!arrival('hrv_avg')} stagger={stagger} />}
              unit={t('app.unit.ms')}
              label={t('today.metric_hrv_avg')}
              sub={
                hrvStatus === null || hrv.corridor === null
                  ? undefined
                  : hrvStatus === 'in'
                    ? t('app.today.in_norm')
                    : t(hrvStatus === 'below' ? 'app.today.below_norm' : 'app.today.above_norm', {
                        lo: formatInt(hrv.corridor.lo, lang),
                        hi: formatInt(hrv.corridor.hi, lang),
                      })
              }
              tone={hrvStatus === 'below' ? 'bad' : undefined}
            />
            {chevron}
          </ScreenLink>
        )}
        {battery !== undefined && (
          <ScreenLink screen="recovery" className="f">
            <FigureBody
              value={<Reading value={battery.value} format={(n) => formatInt(n, lang)} hidden={!arrival('body_battery_high')} stagger={stagger} />}
              label={t('today.metric_body_battery_high')}
              sub={battery.gained === null ? undefined : t('app.today.bb_gained', { value: formatSigned(battery.gained, lang, 0) })}
            />
            {chevron}
          </ScreenLink>
        )}
        {calories !== undefined && (
          <ScreenLink screen="nutrition" className="f">
            <FigureBody
              value={<Reading value={calories.value} format={(n) => formatInt(n, lang)} hidden={!arrival('calories')} stagger={stagger} />}
              unit={t('app.unit.kcal')}
              label={t('today.metric_calories')}
              sub={
                calories.corridor === null
                  ? undefined
                  : t('today.corridor', { min: formatInt(calories.corridor.lo, lang), max: formatInt(calories.corridor.hi, lang) })
              }
            />
            {chevron}
          </ScreenLink>
        )}
      </div>

      <div className="grid">
        <div className="c7">
          <Section className="o2" title={t('app.today.week_title')} meta={t('app.today.week_meta')}>
            {view.changes.length === 0 ? (
              <p className="sub empty-line">{t('today.changes_empty')}</p>
            ) : (
              <div className="rows">
                {view.changes.map((c) => {
                  const digits = CHANGE_DIGITS[c.key] ?? 1
                  const unit = CHANGE_UNIT[c.key]
                  const corridor = c.lo === null || c.hi === null ? null : { lo: c.lo, hi: c.hi }
                  const axis = rangeAxis([c.before, c.after], corridor)
                  const tone = c.tone === '' ? undefined : c.tone
                  return (
                    <ScreenLink key={c.key} screen={MODULE_SCREEN[c.domain_key]?.screen ?? 'today'} className="row dumb">
                      <div>
                        <div className="t">{t(`today.metric_${c.key}`)}</div>
                        <div className="m num">
                          {formatNumber(c.before, lang, digits)} → {formatNumber(c.after, lang, digits)}
                          {unit !== undefined && ` ${t(unit)}`}
                        </div>
                      </div>
                      <RangeBar value={c.after} prev={c.before} lo={c.lo} hi={c.hi} min={axis.min} max={axis.max} tone={tone} />
                      <div className={cx('v', tone)}>{formatSigned(c.after - c.before, lang, digits)}</div>
                    </ScreenLink>
                  )
                })}
              </div>
            )}
          </Section>
          <Section
            className="o3"
            title={t('app.today.day_title')}
            meta={plural(entries, t('app.today.entries.one', { n: entries }), t('app.today.entries.few', { n: entries }), t('app.today.entries.many', { n: entries }))}
          >
            {entries === 0 ? (
              <p className="sub empty-line">{t('today.feed_empty')}</p>
            ) : (
              <div className="feed">
                {view.feed.map((row) => {
                  const line = feedLine(row, t, lang)
                  return (
                    <div key={row.kind === 'weight' ? 'weight' : `${row.kind}:${row.time}:${row.text}`} className={cx('feed-row', row.kind === 'weight' && !hadWeighIn && 'enter')}>
                      <span className="time">{row.time}</span>
                      <span className="rail-dot">
                        <Dot tone={row.dot === 'amber' ? 'accent' : row.dot} />
                      </span>
                      <div>
                        <div className="tx">{line.text}</div>
                        {line.detail !== '' && <div className="dt">{line.detail}</div>}
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
          </Section>
        </div>

        <div className="c5">
          <div className="panel today-log sec o0">
            <div className="panel-h">
              <h3>{t('app.today.weight_today')}</h3>
              {lastWeighed !== null && <span className="sub">{lastWeighed}</span>}
            </div>
            <WeightForm />
            <div className="qchips">
              {modules.nutrition === true && <Chip icon="bowl" tab="meal" label={t('app.log.tab.meal')} />}
              {modules.glp1 === true && <Chip icon="syringe" tab="dose" label={t('app.log.tab.dose')} />}
              <Chip icon="ruler" tab="measure" label={t('app.log.tab.measure')} />
            </div>
          </div>

          <Section className="o1" title={t('app.today.attention_title')} meta={String(view.attention.length)}>
            {view.attention.length === 0 ? (
              <p className="sub empty-line">{t('today.attention_empty')}</p>
            ) : (
              <div className="alerts">
                {(expandedAttention ? view.attention : view.attention.slice(0, 3)).map((item) => {
                  const screen = item.domain === null ? undefined : MODULE_SCREEN[item.domain]?.screen
                  const body = (
                    <>
                      {item.severity === 'note' && <span className="obs">{t('today.observation_prefix')}</span>}
                      {item.message}
                    </>
                  )
                  return screen === undefined ? (
                    <Alert key={`${item.severity}:${item.message}`} tone={item.severity}>
                      {body}
                    </Alert>
                  ) : (
                    <Alert key={`${item.severity}:${item.message}`} as={ScreenLink} screen={screen} tone={item.severity}>
                      {body}
                    </Alert>
                  )
                })}
                {!expandedAttention && view.attention.length > 3 && (
                  <button type="button" className="ghost more-btn" onClick={() => setExpandedAttention(true)}>
                    {t('app.today.attention_more', { count: view.attention.length - 3 })}
                  </button>
                )}
              </div>
            )}
          </Section>

          <Section
            className="o4"
            title={t('app.today.goal_title')}
            meta={
              view.goal === null
                ? undefined
                : view.goal.deadline === null
                  ? t('app.unit.kg_value', { value: formatCompact(view.goal.target_kg, lang) })
                  : t('app.today.goal_meta', { kg: formatCompact(view.goal.target_kg, lang), date: longDate(parseIsoDate(view.goal.deadline), lang) })
            }
          >
            {view.goal === null ? <p className="sub empty-line">{t('today.goal_empty')}</p> : <GoalCard goal={view.goal} />}
          </Section>
        </div>
      </div>
    </>
  )
}

/** The goal as distance covered from where he started, and where the present trend lands. */
function GoalCard({ goal }: { goal: NonNullable<TodayView['goal']> }) {
  const { t, lang, plural } = useT()
  const { done, total, pct } = goalProgress(goal)
  const forecast = goal.forecast
  let forecastLine: string | null = null
  if (forecast !== null) {
    const { key, days } = forecastPhrase(forecast)
    forecastLine = t(key, {
      date: longDate(parseIsoDate(forecast.date), lang),
      n: days,
      days: plural(days, t('app.today.days.one'), t('app.today.days.few'), t('app.today.days.many')),
    })
  }
  return (
    <>
      <div className="goal-top">
        <span className="gv">
          {formatNumber(done, lang)}
          <span className="u">{t('app.today.goal_of', { total: formatCompact(total, lang) })}</span>
        </span>
        <span className="sub num">{formatPercent(pct, lang)}</span>
      </div>
      <Meter value={pct} ticks={[25, 50, 75]} />
      <div className="goal-scale">
        <span>{formatCompact(goal.start_kg, lang)}</span>
        <span>{t('app.now_value', { value: formatNumber(goal.current_kg, lang) })}</span>
        <span>{formatCompact(goal.target_kg, lang)}</span>
      </div>
      {forecastLine !== null && <p className="sub goal-forecast">{forecastLine}</p>}
    </>
  )
}

/** A quick way into the log sheet, on the tab of the entry it names. */
function Chip({ icon, tab, label }: { icon: 'bowl' | 'syringe' | 'ruler'; tab: 'meal' | 'dose' | 'measure'; label: string }) {
  return (
    <button type="button" className="qchip" onClick={() => openLogSheet(tab)}>
      <Icon name={icon} />
      {label}
    </button>
  )
}
