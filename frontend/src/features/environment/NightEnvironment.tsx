import { useMemo, useState } from 'react'
import { Section } from '@/components/controls/Section'
import { Segmented } from '@/components/controls/Segmented'
import { useT } from '@/i18n/useT'
import { parseIsoDate } from '@/lib/dates'
import { formatInt } from '@/lib/format'
import { EnvChart, type CurveStyle } from './EnvChart'
import { co2Model, COLOR, sleepTempModel, spanOf, statsOf, type ChartModel } from './model'
import { parseTs } from './readings'
import { RangeRow } from './RangeRow'
import type { EnvPoint } from './types'
import './environment.css'
import { useEnvironmentEnabled, useEnvironmentNight, useEnvironmentSettings } from './useEnvironmentData'

type Layer = 'co2' | 'temp'

/** The hypnogram's own left margin: the curve under it starts where the hypnogram does. */
const HYPNOGRAM_LEFT = 64

interface NightEnvironmentProps {
  /** The night's date: the day it ends on. */
  date: string
  /** Lights out, minutes since midnight — the hypnogram's axis; null without a recorded night. */
  startMinutes: number | null
  /** How many five-minute blocks the hypnogram spans. */
  blocks: number
}

/** The bedroom's air through the night, on the hypnogram's clock. Not there when the module is off. */
export function NightEnvironment(props: NightEnvironmentProps) {
  return useEnvironmentEnabled() ? <Body {...props} /> : null
}

/** The span the hypnogram covers on the wall clock, and the labels it prints along it. */
export function hypnogramClock(date: string, startMinutes: number, blocks: number): { start: number; end: number; ticks: number[] } {
  const day = parseIsoDate(date)
  // A night that begins in the evening began the day before the date it is filed under.
  const origin = new Date(day.getFullYear(), day.getMonth(), day.getDate() - (startMinutes >= 720 ? 1 : 0))
  const at = (minutes: number) => new Date(origin.getFullYear(), origin.getMonth(), origin.getDate(), 0, minutes).getTime()
  const ticks: number[] = []
  for (let m = Math.ceil(startMinutes / 60) * 60; m - startMinutes <= blocks * 5 - 30; m += 120) ticks.push(at(m))
  return { start: at(startMinutes), end: at(startMinutes + blocks * 5), ticks }
}

function Body({ date, startMinutes, blocks }: NightEnvironmentProps) {
  const { t, lang } = useT()
  const [layer, setLayer] = useState<Layer>('co2')
  const night = useEnvironmentNight(date)
  const settings = useEnvironmentSettings()
  const data = night.data
  const summary = data?.summary
  const th = data?.thresholds ?? settings.data

  const clock = useMemo(
    () => (startMinutes === null || blocks === 0 ? null : hypnogramClock(date, startMinutes, blocks)),
    [date, startMinutes, blocks],
  )
  const span = useMemo(() => {
    if (clock !== null) return [clock.start, clock.end] as const
    return data === undefined ? null : spanOf(data.summary.window, data.series)
  }, [clock, data])

  // Only what falls inside the drawn span: a point outside it would be drawn off the chart.
  const points = useMemo<EnvPoint[]>(() => {
    if (data === undefined || span === null) return []
    return data.series.filter((p) => {
      const at = parseTs(p.ts)
      return at !== null && at >= span[0] && at <= span[1]
    })
  }, [data, span])

  const model: ChartModel | null = useMemo(() => {
    if (th === undefined) return null
    return layer === 'co2' ? co2Model(points, th, 'minute') : sleepTempModel(points, th)
  }, [layer, points, th])

  const styles: Record<string, CurveStyle> = {
    co2: { color: COLOR.co2, label: t('app.env.legend.co2'), name: t('app.env.co2'), unit: t('app.env.ppm'), digits: 0 },
    temp: { color: COLOR.temp, label: t('app.env.legend.temp'), name: t('app.env.temperature'), unit: '°C', digits: 1 },
  }
  const ruleLabels: Record<string, string> =
    th === undefined
      ? {}
      : {
          co2_warn: t('app.env.legend.co2_warn', { v: formatInt(th.co2_warn, lang) }),
          co2_bad: t('app.env.legend.co2_bad', { v: formatInt(th.co2_bad, lang) }),
          temp_min: t('app.env.legend.sleep_range'),
          temp_max: t('app.env.legend.sleep_range'),
        }

  const empty = summary !== undefined && (summary.samples === 0 || points.length === 0)
  // The numbers under the chart are the ones for the span the chart shows: the night, not the
  // morning after it.
  const stats = useMemo(() => statsOf(points), [points])

  return (
    <Section title={t('app.env.sleep.title')}>
      {night.isError && data === undefined ? (
        <p className="m env-none">{t('app.env.sleep.failed')}</p>
      ) : summary === undefined || model === null ? (
        <div className="env-wait" aria-busy="true" />
      ) : empty || span === null ? (
        <p className="m env-none">{t('app.env.sleep.empty')}</p>
      ) : (
        <div className="panel bare">
          <div className="night-groups">
            <Segmented
              value={layer}
              onChange={setLayer}
              label={t('app.env.sleep.layers')}
              options={[
                { id: 'co2', label: t('app.env.sleep.layer_co2') },
                { id: 'temp', label: t('app.env.sleep.layer_temp') },
              ]}
            />
          </div>
          <div className="night-curves">
            <EnvChart
              model={model}
              start={span[0]}
              end={span[1]}
              label={layer === 'co2' ? t('app.env.sleep.chart_co2') : t('app.env.sleep.chart_temp')}
              styles={styles}
              ruleLabels={ruleLabels}
              zones={layer === 'co2' ? th : undefined}
              left={clock === null ? undefined : HYPNOGRAM_LEFT}
              ticks={clock?.ticks}
              height={170}
            />
          </div>
          <div className="env-ranges">
            <RangeRow label={t('app.env.night.temperature')} range={{ min: stats.temperature.min, max: stats.temperature.max }} unit="°C" digits={1} lang={lang} />
            <RangeRow label={t('app.env.night.humidity')} range={{ min: stats.humidity.min, max: stats.humidity.max }} unit="%" digits={0} lang={lang} />
            {stats.co2.median !== null && stats.co2.max !== null && (
              <div className="env-range">
                <span>{t('app.env.co2')}</span>
                <b className="num">
                  {t('app.env.sleep.co2_line', { median: formatInt(stats.co2.median, lang), max: formatInt(stats.co2.max, lang) })}
                </b>
              </div>
            )}
            {th !== undefined && (
              <p className="fhint">{t('app.env.sleep.sleep_range', { lo: th.temp_sleep_min, hi: th.temp_sleep_max })}</p>
            )}
          </div>
        </div>
      )}
    </Section>
  )
}
