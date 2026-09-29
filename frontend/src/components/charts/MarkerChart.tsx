import { useMemo, useRef } from 'react'
import { useLayout } from '@/components/shell/layout'
import { useT } from '@/i18n/useT'
import { monthShort } from '@/lib/dates'
import { formatNumber } from '@/lib/format'
import { useElementWidth } from '@/lib/useElementWidth'
import { ChartFrame } from './ChartFrame'
import { markerGeometry } from './geometry'

interface MarkerChartProps {
  lo: number
  hi: number
  min: number
  max: number
  decimals: number
  history: readonly { date: Date; value: number }[]
  focus?: readonly [number, number]
}

/** One lab marker across draws: its reference range as a band, each result a labelled point,
 *  the ones outside the range in the alarm colour. */
export function MarkerChart({ lo, hi, min, max, decimals, history, focus }: MarkerChartProps) {
  const { t, lang } = useT()
  const { desktop } = useLayout()
  const box = useRef<HTMLDivElement>(null)
  const width = useElementWidth(box)
  const g = useMemo(
    () => markerGeometry({ width, phone: !desktop, lo, hi, min, max, history, focus }),
    [width, desktop, lo, hi, min, max, history, focus],
  )
  const num = (v: number) => formatNumber(v, lang, decimals)

  return (
    <ChartFrame boxRef={box}>
      {width > 0 && (
        <svg width={width} height={g.height} role="img" aria-label={t('app.chart.marker')}>
          <rect x={g.band.x} y={g.band.y} width={g.band.width} height={g.band.height} rx={6} fill="#CEC6D7" fillOpacity=".07" />
          <text className="ax" x={g.band.x + 10} y={g.band.labelY}>
            {t('app.labs.range')}
          </text>
          {g.bounds.map((b) => (
            <g key={b.value}>
              <line x1={g.band.x} x2={g.band.x + g.band.width} y1={b.y} y2={b.y} stroke="#CEC6D7" strokeOpacity=".28" strokeDasharray="3 4" />
              <text className="ax" x={width} y={b.y + 4} textAnchor="end">
                {num(b.value)}
              </text>
            </g>
          ))}
          <path className="draw" pathLength={1} d={g.path} fill="none" stroke="#F4F0F6" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" />
          {g.points.map((p) => (
            <g key={p.date.getTime()} className="late">
              <circle cx={p.x} cy={p.y} r={p.last ? 5 : 3.5} fill={p.out ? '#FF8469' : '#F4F0F6'} stroke="#221E27" strokeWidth={2} />
              <text
                x={p.x}
                y={p.y - 11}
                textAnchor="middle"
                style={{ font: '600 12px var(--f-display)', fill: p.out ? 'var(--bad-strong)' : 'var(--fg-2)', fontVariantNumeric: 'tabular-nums' }}
              >
                {num(p.value)}
              </text>
              <text className="ax" x={p.x} y={g.height - 5} textAnchor="middle">
                {monthShort(p.date, lang)}
              </text>
            </g>
          ))}
        </svg>
      )}
    </ChartFrame>
  )
}
