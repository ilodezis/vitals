import { useMemo, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { api } from '@/api/client'
import { PrimaryButton } from '@/components/controls/PrimaryButton'
import { toast } from '@/components/controls/toast'
import { Icon } from '@/components/icons/Icon'
import { Headline, Mast, TopBar } from '@/components/shell/PageHead'
import { useT } from '@/i18n/useT'
import type { CustomChartItem } from './types'
import { useChartsView } from './useChartsView'
import './charts.css'

const SERIES_COLORS = [
  'var(--accent)',
  'var(--cool)',
  'var(--violet)',
  'var(--good)',
  'var(--warn)',
  '#E056FD',
  '#686DE0',
  '#30336B',
]

interface SeriesDraft {
  domain: string
  metricKey: string
  param?: string
}

export default function ChartsScreen() {
  const { t } = useT()
  const view = useChartsView()
  const queryClient = useQueryClient()

  const [formOpen, setFormOpen] = useState(false)
  const [chartName, setChartName] = useState('')
  const [normalize, setNormalize] = useState(false)
  const [seriesRows, setSeriesRows] = useState<SeriesDraft[]>([
    { domain: 'weight', metricKey: 'ma' },
  ])
  const [isSubmitting, setIsSubmitting] = useState(false)

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ['charts'] })
  }

  const addSeriesRow = () => {
    if (seriesRows.length >= 8) {
      toast('Максимум 8 рядов на графике', { icon: 'warn' })
      return
    }
    setSeriesRows([...seriesRows, { domain: 'garmin', metricKey: 'sleep' }])
  }

  const removeSeriesRow = (index: number) => {
    if (seriesRows.length <= 1) return
    setSeriesRows(seriesRows.filter((_, i) => i !== index))
  }

  const updateSeriesRow = (index: number, patch: Partial<SeriesDraft>) => {
    setSeriesRows((prev) =>
      prev.map((row, i) => (i === index ? { ...row, ...patch } : row))
    )
  }

  const handleSaveChart = async (): Promise<boolean> => {
    if (!chartName.trim()) {
      toast('Введите название графика', { icon: 'warn' })
      return false
    }
    setIsSubmitting(true)
    try {
      await api.POST('/api/v1/charts', {
        body: {
          name: chartName.trim(),
          normalize,
          series: seriesRows.map((r) => ({
            domain: r.domain,
            metricKey: r.metricKey,
            param: r.param || null,
          })),
        },
      })
      toast('График сохранён')
      setFormOpen(false)
      setChartName('')
      refresh()
      return true
    } catch (err: any) {
      toast(err.message || 'Не удалось сохранить график', { icon: 'warn' })
      return false
    } finally {
      setIsSubmitting(false)
    }
  }

  const handleDeleteChart = async (id: string) => {
    try {
      await api.DELETE('/api/v1/charts/{chart_id}', {
        params: { path: { chart_id: id } },
      })
      toast(t('common.deleted'))
      refresh()
    } catch (err: any) {
      toast(err.message || 'Error deleting chart', { icon: 'warn' })
    }
  }

  const renderSvgChart = (chart: CustomChartItem) => {
    const allPoints = chart.series.flatMap((s) => s.points)
    if (!allPoints.length) {
      return (
        <div className="py-12 text-center text-sm text-[var(--muted)]">
          Нет данных за выбранный период
        </div>
      )
    }

    const values = allPoints.map((p) => p.value)
    const minVal = Math.min(...values)
    const maxVal = Math.max(...values)
    const valRange = maxVal - minVal || 1

    const w = 480
    const h = 180
    const padX = 24
    const padY = 16

    return (
      <svg viewBox={`0 0 ${w} ${h}`} className="w-full h-auto overflow-visible">
        {/* Horizontal grid lines */}
        <line
          x1={padX}
          y1={padY}
          x2={w - padX}
          y2={padY}
          stroke="var(--line)"
          strokeWidth="1"
        />
        <line
          x1={padX}
          y1={h / 2}
          x2={w - padX}
          y2={h / 2}
          stroke="var(--line)"
          strokeWidth="1"
        />
        <line
          x1={padX}
          y1={h - padY}
          x2={w - padX}
          y2={h - padY}
          stroke="var(--line)"
          strokeWidth="1"
        />

        {/* Polylines for each series */}
        {chart.series.map((s, sIdx) => {
          if (!s.points.length) return null
          const color = SERIES_COLORS[s.colorSlot % SERIES_COLORS.length]
          const coords = s.points.map((p, i) => {
            const x = padX + (i / Math.max(s.points.length - 1, 1)) * (w - 2 * padX)
            const y = h - padY - ((p.value - minVal) / valRange) * (h - 2 * padY)
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

  const catalogDomains = useMemo(() => {
    return [
      { key: 'weight', label: 'Вес' },
      { key: 'garmin', label: 'Garmin' },
      { key: 'workouts', label: 'Тренировки' },
      { key: 'nutrition', label: 'Питание' },
      { key: 'labs', label: 'Анализы' },
    ]
  }, [])

  return (
    <>
      <TopBar
        title={t('nav.charts')}
        right={
          <button
            type="button"
            className="ibtn"
            onClick={() => setFormOpen(true)}
            aria-label="Новый график"
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
            <span>Новый график</span>
          </button>
        }
      />
      <Headline title={t('nav.charts')}>
        <div className="figs inline">
          <div className="f">
            <div className="f-v">{view.count || view.charts.length}</div>
            <div className="f-l">Графиков</div>
          </div>
        </div>
      </Headline>

      {/* New Chart Constructor Form Modal */}
      {formOpen && (
        <div className="panel fpanel mb-6" style={{ marginTop: 'var(--s6)' }}>
          <div className="panel-h">
            <h3>Новый график</h3>
            <button type="button" className="ibtn" onClick={() => setFormOpen(false)}>
              <Icon name="x" />
            </button>
          </div>
          <div className="form space-y-4">
            <label className="field">
              <span className="flabel">Название графика</span>
              <input
                className="input"
                placeholder="например, Вес и сон"
                value={chartName}
                onChange={(e) => setChartName(e.target.value)}
              />
            </label>

            {/* Series rows */}
            <div className="srows">
              {seriesRows.map((r, i) => (
                <div key={i} className="srow">
                  <span className="flabel">Ряд {i + 1}</span>
                  <div className="srow-f">
                    <select
                      className="input"
                      value={r.domain}
                      onChange={(e) => updateSeriesRow(i, { domain: e.target.value })}
                    >
                      {catalogDomains.map((d) => (
                        <option key={d.key} value={d.key}>
                          {d.label}
                        </option>
                      ))}
                    </select>
                    <input
                      className="input"
                      placeholder="Ключ метрики (напр. ma, sleep, rhr)"
                      value={r.metricKey}
                      onChange={(e) => updateSeriesRow(i, { metricKey: e.target.value })}
                    />
                  </div>
                  {seriesRows.length > 1 && (
                    <button
                      type="button"
                      className="ibtn"
                      onClick={() => removeSeriesRow(i)}
                      aria-label="Удалить"
                    >
                      <Icon name="x" />
                    </button>
                  )}
                </div>
              ))}
            </div>

            <button type="button" className="ghost" onClick={addSeriesRow}>
              <Icon name="plus" />
              <span>Добавить метрику</span>
            </button>

            <label className="flex items-center gap-2 cursor-pointer pt-1">
              <input
                type="checkbox"
                checked={normalize}
                onChange={(e) => setNormalize(e.target.checked)}
              />
              <span className="text-sm">Нормализовать (индекс = 100 в начале)</span>
            </label>

            <div className="form-acts flex gap-2 pt-2">
              <PrimaryButton
                className="btn grow"
                onPress={handleSaveChart}
                disabled={isSubmitting}
              >
                Сохранить график
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
        <div className="cgal mt-6">
          {view.charts.map((c) => (
            <section key={c.id} className="sec cg" data-item>
              <div className="sec-h">
                <h2>{c.name}</h2>
                <span className="acts">
                  <button
                    type="button"
                    className="ghost danger"
                    onClick={() => handleDeleteChart(c.id)}
                  >
                    <Icon name="trash" />
                    <span>Удалить</span>
                  </button>
                </span>
              </div>
              {c.normalize && (
                <p className="meta cg-note">индекс = 100 в начале</p>
              )}
              <div className="panel bare">
                <div className="chart">{renderSvgChart(c)}</div>
                <div className="legend">
                  {c.series.map((s, idx) => {
                    const color = SERIES_COLORS[s.colorSlot % SERIES_COLORS.length]
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
                      события хронологии
                    </span>
                  )}
                  <span>
                    <i className="now" />
                    сейчас
                  </span>
                </div>
              </div>
            </section>
          ))}
        </div>
      ) : (
        <div className="empty mt-6">
          <Icon name="chart" />
          <p>Пока нет кастомных графиков.</p>
          <small>Соберите первый: до восьми рядов на одном графике.</small>
        </div>
      )}
    </>
  )
}
