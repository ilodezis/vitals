import { Link } from '@tanstack/react-router'
import { Alert } from '@/components/controls/Alert'
import { FigureBody, Section } from '@/components/controls/Section'
import { Icon } from '@/components/icons/Icon'
import { useT } from '@/i18n/useT'
import { clockLabel } from '@/lib/dates'
import { formatInt, type Lang } from '@/lib/format'
import type { TFn } from '@/lib/units'
import { co2ZoneOf, minutesText, parseTs } from './readings'
import { RangeRow } from './RangeRow'
import type { EnvSummary, EnvThresholds } from './types'
import { useEnvironmentNight } from './useEnvironmentData'

/** The coverage below which the night's figures are called partial. */
const SPARSE_PCT = 60

/** Last night's air: CO₂ against the thresholds, the ranges of temperature and humidity, and the way
 *  to the night itself. */
export function NightSection({ date, thresholds }: { date: string; thresholds: EnvThresholds }) {
  const { t, lang } = useT()
  const night = useEnvironmentNight(date)
  const summary = night.data?.summary

  return (
    <Section title={t('app.env.last_night')} meta={summary === undefined ? undefined : windowText(summary, t, lang)}>
      {night.isError && summary === undefined ? (
        <Alert tone="warn" actions={<button type="button" className="ghost" onClick={() => void night.refetch()}>{t('app.retry')}</button>}>
          {t('app.env.load_failed')}
        </Alert>
      ) : summary === undefined ? (
        <div className="env-wait" aria-busy="true" />
      ) : summary.samples === 0 ? (
        <p className="m env-none">{t('app.env.night.empty')}</p>
      ) : (
        <>
          {summary.coverage_pct < SPARSE_PCT && (
            <Alert tone="info" className="env-alert">
              {t('app.env.night.sparse', { pct: formatInt(summary.coverage_pct, lang) })}
            </Alert>
          )}
          <div className="figs env-night-figs">
            <div className="f">
              <FigureBody
                value={ppm(summary.co2.median, lang)}
                unit={summary.co2.median == null ? '' : t('app.env.ppm')}
                label={t('app.env.night.co2_median')}
              />
            </div>
            <div className="f">
              <FigureBody
                value={ppm(summary.co2.max, lang)}
                unit={summary.co2.max == null ? '' : t('app.env.ppm')}
                label={t('app.env.night.co2_max')}
                sub={summary.co2.max == null ? undefined : t(`app.env.zone.${co2ZoneOf(summary.co2.max, thresholds)}`)}
              />
            </div>
            <div className="f">
              <FigureBody
                value={minutesText(summary.co2.minutes_above_warn, t)}
                label={t('app.env.night.above', { v: formatInt(thresholds.co2_warn, lang) })}
              />
            </div>
            <div className="f">
              <FigureBody
                value={minutesText(summary.co2.minutes_above_bad, t)}
                label={t('app.env.night.above', { v: formatInt(thresholds.co2_bad, lang) })}
              />
            </div>
          </div>
          <div className="env-ranges">
            <RangeRow label={t('app.env.night.temperature')} range={summary.temperature} unit="°C" digits={1} lang={lang} />
            <RangeRow label={t('app.env.night.humidity')} range={summary.humidity} unit="%" digits={0} lang={lang} />
          </div>
        </>
      )}
      <Link to="/recovery/sleep/$date" params={{ date }} className="env-night-link">
        <span>{t('app.env.night.link')}</span>
        <Icon name="chevR" />
      </Link>
    </Section>
  )
}

const ppm = (v: number | null | undefined, lang: Lang): string => (v == null ? '—' : formatInt(v, lang))

/** "00:00–12:00 · coverage 96%": the window the night's figures are taken over. */
function windowText(summary: EnvSummary, t: TFn, lang: Lang): string | undefined {
  const a = parseTs(summary.window.start)
  const b = parseTs(summary.window.end)
  if (a === null || b === null) return undefined
  return t('app.env.night.meta', {
    start: clockLabel(new Date(a)),
    end: clockLabel(new Date(b)),
    pct: formatInt(summary.coverage_pct, lang),
  })
}
