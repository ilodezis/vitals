import { useMemo, useState } from 'react'
import { Alert } from '@/components/controls/Alert'
import { Section } from '@/components/controls/Section'
import { Segmented } from '@/components/controls/Segmented'
import { useT } from '@/i18n/useT'
import { formatInt } from '@/lib/format'
import { EnvChart, type CurveStyle } from './EnvChart'
import { WINDOWS, type WindowHours } from './environmentApi'
import { climateModel, co2Model, COLOR, spanOf } from './model'
import type { EnvThresholds } from './types'
import { useEnvironmentSeries } from './useEnvironmentData'

/** The last 6, 24 or 72 hours: CO₂ with its thresholds, then temperature and humidity each on its
 *  own scale. */
export function TodaySection({ thresholds, inView }: { thresholds: EnvThresholds; inView: boolean }) {
  const { t, lang } = useT()
  const [hours, setHours] = useState<WindowHours>(24)
  const series = useEnvironmentSeries(hours, inView)
  const data = series.data
  const resolution = data?.resolution ?? 'minute'
  const points = useMemo(() => data?.points ?? [], [data])
  const th = data?.thresholds ?? thresholds
  const span = useMemo(() => spanOf(data?.window, points), [data, points])

  const co2 = useMemo(() => co2Model(points, th, resolution), [points, th, resolution])
  const climate = useMemo(() => climateModel(points, th, resolution), [points, th, resolution])
  const hasData = points.length > 0 && span !== null

  const co2Styles: Record<string, CurveStyle> = {
    co2: { color: COLOR.co2, label: t('app.env.legend.co2'), name: t('app.env.co2'), unit: t('app.env.ppm'), digits: 0 },
  }
  const climateStyles: Record<string, CurveStyle> = {
    temp: { color: COLOR.temp, label: t('app.env.legend.temp'), name: t('app.env.temperature'), unit: '°C', digits: 1 },
    rh: { color: COLOR.rh, label: t('app.env.legend.rh'), name: t('app.env.humidity'), unit: '%', digits: 0 },
  }
  const ruleLabels = {
    co2_warn: t('app.env.legend.co2_warn', { v: formatInt(th.co2_warn, lang) }),
    co2_bad: t('app.env.legend.co2_bad', { v: formatInt(th.co2_bad, lang) }),
  }
  const comfort = t('app.env.legend.comfort')
  const climateRuleLabels = { temp_min: comfort, temp_max: comfort, rh_min: comfort, rh_max: comfort }

  const meta = data === undefined ? undefined : t('app.env.coverage', { pct: formatInt(data.coverage_pct, lang) })

  return (
    <Section title={t('app.env.today')} meta={meta}>
      <div className="env-window">
        <Segmented
          value={String(hours) as `${WindowHours}`}
          onChange={(id) => setHours(Number(id) as WindowHours)}
          label={t('app.env.window_label')}
          options={WINDOWS.map((h) => ({ id: String(h) as `${WindowHours}`, label: t(`app.env.window.${h}`) }))}
        />
      </div>

      {series.isError && data === undefined ? (
        <Alert tone="warn" actions={<button type="button" className="ghost" onClick={() => void series.refetch()}>{t('app.retry')}</button>}>
          {t('app.env.load_failed')}
        </Alert>
      ) : data === undefined ? (
        <div className="env-wait" aria-busy="true" />
      ) : !hasData ? (
        <p className="m env-none">{t('app.env.no_data')}</p>
      ) : (
        <div className="panel bare env-charts">
          <EnvChart
            model={co2}
            start={span[0]}
            end={span[1]}
            label={t('app.env.chart.co2', { hours })}
            styles={co2Styles}
            ruleLabels={ruleLabels}
            bandLabel={t('app.env.legend.peaks')}
            zones={th}
          />
          <EnvChart
            model={climate}
            start={span[0]}
            end={span[1]}
            label={t('app.env.chart.climate', { hours })}
            styles={climateStyles}
            ruleLabels={climateRuleLabels}
          />
        </div>
      )}
    </Section>
  )
}
