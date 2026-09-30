import { useId, useMemo, useRef } from 'react'
import { useLayout } from '@/components/shell/layout'
import { useT } from '@/i18n/useT'
import { addDays, shortDate } from '@/lib/dates'
import { formatNumber } from '@/lib/format'
import { useElementWidth } from '@/lib/useElementWidth'
import { ChartFrame } from './ChartFrame'
import { trendGeometry } from './geometry'

export type TrendRange = '1m' | '3m' | 'all'
const RANGE_DAYS: Record<TrendRange, number> = { '1m': 30, '3m': 92, all: 9999 }

interface TrendChartProps {
  weighings: readonly { date: Date; kg: number }[]
  trend: readonly { date: Date; kg: number }[]
  phases: readonly { from: Date; to: Date; label: string }[]
  range: TrendRange
  /** The last day drawn. */
  end: Date
}

/** Weight over time: each weighing a dot, the 7-day trend a line that draws itself, the dose
 *  phases shaded behind, and today a pulsing amber point. */
export function TrendChart({ weighings, trend, phases, range, end }: TrendChartProps) {
  const { t, lang } = useT()
  const { desktop } = useLayout()
  const box = useRef<HTMLDivElement>(null)
  const width = useElementWidth(box)
  const gradient = useId()

  const from = useMemo(() => {
    const first = trend[0]?.date ?? end
    const earliest = addDays(end, -RANGE_DAYS[range])
    return first > earliest ? first : earliest
  }, [trend, end, range])

  const geometry = useMemo(
    () =>
      trendGeometry({
        width,
        phone: !desktop,
        weighings: weighings.filter((p) => p.date >= from),
        trend: trend.filter((p) => p.date >= from),
        phases,
        end,
      }),
    [width, desktop, weighings, trend, phases, end, from],
  )
  const g = geometry
  const tick = (v: number) => formatNumber(v, lang, v % 1 === 0 ? 0 : 1)

  const clipId = useId()

  return (
    <ChartFrame boxRef={box} scrub={g.scrub} readout={(p) => t('app.unit.kg_value', { value: formatNumber(p.value, lang) })}>
      {width > 0 && (
        <svg key={range} width={width} height={g.height} viewBox={`0 0 ${width} ${g.height}`} role="img" aria-label={t('app.chart.weight')}>
          <defs>
            <linearGradient id={gradient} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0" stopColor="#F4F0F6" stopOpacity=".07" />
              <stop offset="1" stopColor="#F4F0F6" stopOpacity="0" />
            </linearGradient>
            <clipPath id={clipId}>
              <rect x={0} y={0} width={width - 36 + 6} height={g.height} />
            </clipPath>
          </defs>
          {g.phases.map((ph) => (
            <g key={ph.index}>
              <rect x={ph.x} y={g.top - 10} width={ph.width} height={g.height - g.top - g.bottom + 10} fill="#BCA4DC" fillOpacity={ph.index > 0 ? 0.05 : 0.03} />
              <line x1={ph.x} x2={ph.x} y1={g.top - 10} y2={g.height - g.bottom} stroke="#BCA4DC" strokeOpacity=".35" strokeDasharray="2 3" />
              {ph.label !== null && (
                <text x={ph.x + 7} y={g.top + 2} className="ax" style={{ fill: 'var(--violet)' }}>
                  {ph.label}
                </text>
              )}
            </g>
          ))}
          {g.yTicks.map((y) => (
            <g key={y.value}>
              <line className="grid" x1={0} x2={width - 36 + 6} y1={y.y} y2={y.y} />
              <text className="ax" x={width} y={y.y + 4} textAnchor="end">
                {tick(y.value)}
              </text>
            </g>
          ))}
          {g.xTicks.map((x, i) => (
            <text key={i} className="ax" x={x.x} y={g.height - 6} textAnchor={x.anchor}>
              {shortDate(x.date, lang)}
            </text>
          ))}
          <g clipPath={`url(#${clipId})`}>
            {g.areaPath !== '' && <path className="late" d={g.areaPath} fill={`url(#${gradient})`} />}
            <g className="late">
              {g.dots.map((p, i) => (
                <circle key={i} cx={p.x.toFixed(1)} cy={p.y.toFixed(1)} r={desktop ? 2.4 : 2} fill="#857B93" />
              ))}
            </g>
            <path className="draw" pathLength={1} d={g.trendPath} fill="none" stroke="#F4F0F6" strokeWidth={2} strokeLinecap="round" />
            {g.now !== null && (
              <g className="late">
                <circle className="now-ring" cx={g.now.x} cy={g.now.y} r={4} fill="#F5A623" />
                <circle cx={g.now.x} cy={g.now.y} r={4.5} fill="#F5A623" stroke="#221E27" strokeWidth={2} />
              </g>
            )}
          </g>
        </svg>
      )}
    </ChartFrame>
  )
}
