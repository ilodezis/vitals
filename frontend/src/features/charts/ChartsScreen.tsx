import { useMemo, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { api, ok, failText } from '@/api/client'
import { PrimaryButton } from '@/components/controls/PrimaryButton'
import { TextButton } from '@/components/controls/Marks'
import { toast } from '@/components/controls/toast'
import { Icon } from '@/components/icons/Icon'
import { Headline, Mast, TopBar } from '@/components/shell/PageHead'
import { useT } from '@/i18n/useT'
import { parseIsoDate, shortDate } from '@/lib/dates'
import { cx } from '@/lib/cx'
import { formatNumber } from '@/lib/format'
import { emptySeries, MAX_SERIES, metricOf, metricOptionLabel, metricsOf, needsParam, pickDomain, pickMetric, readCatalog, rowReady, seriesBody, type SeriesDraft } from './catalog'
import { seriesColor } from './seriesColors'
import type { CustomChartItem } from './types'
import { useChartsView } from './useChartsView'
import './charts.css'

export default function ChartsScreen() {
  const { t, lang } = useT()
  const view = useChartsView()
  const queryClient = useQueryClient()

  const [formOpen, setFormOpen] = useState(false)
  const [chartName, setChartName] = useState('')
  const [normalize, setNormalize] = useState(false)
  const domains = useMemo(() => readCatalog(view.catalog), [view.catalog])
  const [seriesRows, setSeriesRows] = useState<SeriesDraft[]>([emptySeries()])
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null)

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ['charts'] })
  }

  const addSeriesRow = () => {
    if (seriesRows.length >= MAX_SERIES) {
      toast(t('app.charts.max_8_series'), { icon: 'warn' })
      return
    }
    setSeriesRows([...seriesRows, emptySeries()])
  }

  const removeSeriesRow = (index: number) => {
    if (seriesRows.length <= 1) return
    setSeriesRows(seriesRows.filter((_, i) => i !== index))
  }

  const updateSeriesRow = (index: number, change: (row: SeriesDraft) => SeriesDraft) => {
    setSeriesRows((prev) => prev.map((row, i) => (i === index ? change(row) : row)))
  }

  const handleSaveChart = async (): Promise<boolean> => {
    if (!chartName.trim()) {
      toast(t('app.charts.enter_name'), { icon: 'warn' })
      return false
    }
    if (!seriesRows.every((r) => rowReady(domains, r))) {
      toast(t('app.charts.pick_all'), { icon: 'warn' })
      return false
    }
    setIsSubmitting(true)
    try {
      await ok(api.POST('/api/v1/charts', {
        body: {
          name: chartName.trim(),
          normalize,
          series: seriesRows.map((r) => seriesBody(domains, r)),
        },
      }))
      toast(t('app.charts.chart_saved'))
      setFormOpen(false)
      setChartName('')
      setSeriesRows([emptySeries()])
      refresh()
      return true
    } catch (err) {
      toast(failText(err, t('app.charts.save_failed')), { icon: 'warn' })
      return false
    } finally {
      setIsSubmitting(false)
    }
  }

  const handleDeleteChart = async (id: string) => {
    if (confirmDeleteId !== id) {
      setConfirmDeleteId(id)
      return
    }
    setConfirmDeleteId(null)
    try {
      await ok(api.DELETE('/api/v1/charts/{chart_id}', {
        params: { path: { chart_id: id } },
      }))
      toast(t('common.deleted'))
      refresh()
    } catch (err) {
      toast(failText(err, t('app.charts.delete_failed')), { icon: 'warn' })
    }
  }

  const renderSvgChart = (chart: CustomChartItem) => {
    const allPoints = chart.series.flatMap((s) => s.points)
    if (!allPoints.length) {
      return (
        <div className="chart-empty">
          {t('app.charts.no_data_period')}
        </div>
      )
    }

    const values = allPoints.map((p) => p.value)
    const minVal = Math.min(...values)
    const maxVal = Math.max(...values)
    const midVal = (minVal + maxVal) / 2
    const valRange = maxVal - minVal || 1

    // Dates for X-axis
    const allDates = allPoints.map((p) => p.date).sort()
    const firstDateStr = allDates[0]
    const firstDate = firstDateStr ? shortDate(parseIsoDate(firstDateStr), lang) : ''
    const lastDateStr = allDates[allDates.length - 1]
    const lastDate = lastDateStr ? shortDate(parseIsoDate(lastDateStr), lang) : ''

    const w = 480
    const h = 180
    const padLeft = 40
    const padRight = 16
    const padTop = 18
    const padBottom = 26

    const plotW = w - padLeft - padRight
    const plotH = h - padTop - padBottom

    return (
      <svg viewBox={`0 0 ${w} ${h}`} className="chart-svg">
        {/* Horizontal grid lines */}
        <line
          x1={padLeft}
          y1={padTop}
          x2={w - padRight}
          y2={padTop}
          stroke="var(--line)"
          strokeWidth="1"
        />
        <line
          x1={padLeft}
          y1={padTop + plotH / 2}
          x2={w - padRight}
          y2={padTop + plotH / 2}
          stroke="var(--line)"
          strokeWidth="1"
          strokeDasharray="2,2"
        />
        <line
          x1={padLeft}
          y1={padTop + plotH}
          x2={w - padRight}
          y2={padTop + plotH}
          stroke="var(--line)"
          strokeWidth="1"
        />

        {/* Y-axis Ticks */}
        <text
          x={padLeft - 6}
          y={padTop + 3}
          textAnchor="end"
          fill="var(--muted)"
          fontSize="10"
          fontFamily="var(--f-text)"
        >
          {formatNumber(maxVal, lang, maxVal >= 100 ? 0 : 1)}
        </text>
        <text
          x={padLeft - 6}
          y={padTop + plotH / 2 + 3}
          textAnchor="end"
          fill="var(--muted)"
          fontSize="10"
          fontFamily="var(--f-text)"
        >
          {formatNumber(midVal, lang, midVal >= 100 ? 0 : 1)}
        </text>
        <text
          x={padLeft - 6}
          y={padTop + plotH + 3}
          textAnchor="end"
          fill="var(--muted)"
          fontSize="10"
          fontFamily="var(--f-text)"
        >
          {formatNumber(minVal, lang, minVal >= 100 ? 0 : 1)}
        </text>

        {/* X-axis start/end dates */}
        {firstDate && (
          <text
            x={padLeft}
            y={h - 6}
            fill="var(--muted)"
            fontSize="10"
            fontFamily="var(--f-text)"
          >
            {firstDate}
          </text>
        )}
        {lastDate && (
          <text
            x={w - padRight}
            y={h - 6}
            textAnchor="end"
            fill="var(--muted)"
            fontSize="10"
            fontFamily="var(--f-text)"
          >
            {lastDate}
          </text>
        )}

        {/* Polylines for each series */}
        {chart.series.map((s, sIdx) => {
          if (!s.points.length) return null
          const color = seriesColor(s.colorSlot)
          const coords = s.points.map((p, i) => {
            const x = padLeft + (i / Math.max(s.points.length - 1, 1)) * plotW
            const y = padTop + plotH - ((p.value - minVal) / valRange) * plotH
            return `${x.toFixed(1)},${y.toFixed(1)}`
          })

          return (
            <polyline
              key={sIdx}
              fill="none"
              stroke={color}
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
              points={coords.join(' ')}
            />
          )
        })}
      </svg>
    )
  }

  return (
    <>
      <TopBar
        title={t('nav.charts')}
        right={
          <button
            type="button"
            className="ibtn"
            onClick={() => setFormOpen(true)}
            aria-label={t('app.charts.new_chart')}
          >
            <Icon name="plus" />
          </button>
        }
      />
      <Mast
        screen="charts"
        actions={
          <button type="button" className="ghost" onClick={() => setFormOpen(true)}>
            <Icon name="plus" />
            <span>{t('app.charts.new_chart')}</span>
          </button>
        }
      />
      <Headline title={t('nav.charts')}>
        <div className="figs inline">
          <div className="f">
            <div className="f-v">{view.count || view.charts.length}</div>
            <div className="f-l">{t('app.charts.charts_count')}</div>
          </div>
        </div>
      </Headline>

      {/* New Chart Constructor Form Modal */}
      {formOpen && (
        <div className="panel fpanel">
          <div className="panel-h">
            <h3>{t('app.charts.new_chart')}</h3>
            <button type="button" className="ibtn" onClick={() => setFormOpen(false)}>
              <Icon name="x" />
            </button>
          </div>
          <div className="form">
            <label className="field">
              <span className="flabel">{t('app.charts.chart_name')}</span>
              <input
                className="input"
                placeholder={t('app.charts.name_placeholder')}
                value={chartName}
                onChange={(e) => setChartName(e.target.value)}
              />
            </label>

            {/* Series rows */}
            <div className="srows">
              {seriesRows.map((r, i) => (
                <div key={i} className="srow">
                  <span className="flabel">{t('app.charts.row_n', { n: i + 1 })}</span>
                  <div className="srow-f">
                    <select
                      className="input"
                      aria-label={t('app.charts.domain')}
                      value={r.domain}
                      onChange={(e) => updateSeriesRow(i, (row) => pickDomain(row, e.target.value))}
                    >
                      <option value="" disabled>
                        {t('app.charts.pick_domain')}
                      </option>
                      {domains.map((d) => (
                        <option key={d.key} value={d.key}>
                          {d.label}
                        </option>
                      ))}
                    </select>
                    <select
                      className="input"
                      aria-label={t('app.charts.metric')}
                      value={r.metricKey}
                      disabled={r.domain === ''}
                      onChange={(e) => updateSeriesRow(i, (row) => pickMetric(row, e.target.value))}
                    >
                      <option value="" disabled>
                        {t('app.charts.pick_metric')}
                      </option>
                      {metricsOf(domains, r.domain).map((m) => (
                        <option key={m.key} value={m.key}>
                          {metricOptionLabel(m)}
                        </option>
                      ))}
                    </select>
                    {needsParam(metricOf(domains, r.domain, r.metricKey)) && (
                      <select
                        className="input"
                        aria-label={t('app.charts.param')}
                        value={r.param}
                        onChange={(e) => updateSeriesRow(i, (row) => ({ ...row, param: e.target.value }))}
                      >
                        <option value="" disabled>
                          {(metricOf(domains, r.domain, r.metricKey)?.params.length ?? 0) > 0 ? t('app.charts.pick_param') : t('app.charts.no_params')}
                        </option>
                        {metricOf(domains, r.domain, r.metricKey)?.params.map((p) => (
                          <option key={p.value} value={p.value}>
                            {p.label}
                          </option>
                        ))}
                      </select>
                    )}
                  </div>
                  {seriesRows.length > 1 && (
                    <button
                      type="button"
                      className="ibtn"
                      onClick={() => removeSeriesRow(i)}
                      aria-label={t('common.delete')}
                    >
                      <Icon name="x" />
                    </button>
                  )}
                </div>
              ))}
            </div>

            {seriesRows.length < MAX_SERIES && (
            <button type="button" className="ghost" onClick={addSeriesRow}>
              <Icon name="plus" />
              <span>{t('app.charts.add_metric')}</span>
            </button>
            )}

            <button type="button" className={cx('tgl', normalize && 'on')} aria-pressed={normalize} onClick={() => setNormalize(!normalize)}>
              <i />
              {t('app.charts.normalize_label')}
            </button>

            <div className="form-acts">
              <PrimaryButton
                className="btn grow"
                onPress={handleSaveChart}
                disabled={isSubmitting}
              >
                {t('app.charts.save_chart')}
              </PrimaryButton>
              <button
                type="button"
                className="ghost"
                onClick={() => setFormOpen(false)}
              >
                {t('common.cancel')}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Charts Gallery */}
      {view.charts.length > 0 ? (
        <div className="cgal">
          {view.charts.map((c) => (
            <section key={c.id} className="sec cg" data-item>
              <div className="sec-h">
                <h2>{c.name}</h2>
                <span className="acts">
                  <TextButton
                    icon={confirmDeleteId === c.id ? 'warn' : 'trash'}
                    danger={confirmDeleteId === c.id}
                    onClick={() => handleDeleteChart(c.id)}
                  >
                    {confirmDeleteId === c.id ? t('common.confirm_question') : t('common.delete')}
                  </TextButton>
                </span>
              </div>
              {c.normalize && (
                <p className="meta cg-note">{t('app.charts.normalized_note')}</p>
              )}
              <div className="panel bare">
                <div className="chart">{renderSvgChart(c)}</div>
                <div className="legend">
                  {c.series.map((s, idx) => {
                    const color = seriesColor(s.colorSlot)
                    return (
                      <span key={idx}>
                        <i style={{ background: color }} />
                        {s.label}
                      </span>
                    )
                  })}
                  {c.overlays?.length > 0 && (
                    <span>
                      <i className="band" />
                      {t('app.charts.timeline_events')}
                    </span>
                  )}
                  <span>
                    <i className="now" />
                    {t('app.now')}
                  </span>
                </div>
              </div>
            </section>
          ))}
        </div>
      ) : (
        <div className="empty charts-empty">
          <Icon name="chart" />
          <p>{t('app.charts.empty_title')}</p>
          <small>{t('app.charts.empty_desc')}</small>
        </div>
      )}
    </>
  )
}
