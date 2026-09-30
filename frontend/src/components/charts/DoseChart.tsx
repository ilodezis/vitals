import { useId, useMemo, useRef } from 'react'
import { useLayout } from '@/components/shell/layout'
import { useT } from '@/i18n/useT'
import { monthShort } from '@/lib/dates'
import { formatNumber } from '@/lib/format'
import { useElementWidth } from '@/lib/useElementWidth'
import { ChartFrame } from './ChartFrame'
import { doseGeometry } from './geometry'

interface DoseChartProps {
  phases: readonly { from: Date; doseMg: number }[]
  trend: readonly { date: Date; kg: number }[]
  start: Date
  end: Date
}

const READING = { font: '600 12px var(--f-display)', fontVariantNumeric: 'tabular-nums' } as const

/** The dose as steps (violet) over the weight trend: what changed, and when the weight followed. */
export function DoseChart({ phases, trend, start, end }: DoseChartProps) {
  const { t, lang } = useT()
  const { desktop } = useLayout()
  const box = useRef<HTMLDivElement>(null)
  const width = useElementWidth(box)
  const clipId = useId()
  const g = useMemo(
    () => doseGeometry({ width, phone: !desktop, phases, trend, start, end }),
    [width, desktop, phases, trend, start, end],
  )
  const kg = (v: number) => t('app.unit.kg_value', { value: formatNumber(v, lang) })

  return (
    <ChartFrame boxRef={box}>
      {width > 0 && (
        <svg width={width} height={g.height} role="img" aria-label={t('app.chart.dose')}>
          <defs>
            <clipPath id={clipId}>
              <rect x={0} y={0} width={width} height={g.height} />
            </clipPath>
          </defs>
          {g.levels.map((l) => (
            <g key={l.dose}>
              <line className="grid" x1={2} x2={width - 38 + 4} y1={l.y} y2={l.y} />
              <text className="ax" x={width} y={l.y + 4} textAnchor="end" style={{ fill: 'var(--violet)' }}>
                {formatNumber(l.dose, lang, 2)}
              </text>
            </g>
          ))}
          <line className="grid" x1={2} x2={width - 38 + 4} y1={g.bottom} y2={g.bottom} />
          <g clipPath={`url(#${clipId})`}>
            <path className="draw" pathLength={1} d={g.stepPath} fill="none" stroke="#BCA4DC" strokeWidth={2} strokeLinejoin="round" />
            <path className="draw" pathLength={1} d={g.weightPath} fill="none" stroke="#F4F0F6" strokeOpacity=".75" strokeWidth={1.75} />
          </g>
          {g.last !== null && g.first !== null && (
            <g className="late">
              <text x={g.last.x - 4} y={Math.min(g.bottom - 4, Math.max(16, g.last.y + 22))} textAnchor="end" style={{ ...READING, fill: 'var(--fg-2)' }}>
                {kg(g.last.kg)}
              </text>
              <text x={g.first.x + 4} y={Math.min(g.bottom - 4, Math.max(16, g.first.y - 10))} style={{ ...READING, fill: 'var(--muted)' }}>
                {kg(g.first.kg)}
              </text>
              <circle className="now-ring" cx={g.last.x} cy={g.last.y} r={4} fill="#F5A623" />
              <circle cx={g.last.x} cy={g.last.y} r={4.5} fill="#F5A623" stroke="#221E27" strokeWidth={2} />
            </g>
          )}
          {g.months.map((m) => (
            <text key={m.date.getTime()} className="ax" x={m.x} y={g.height - 5} textAnchor="middle">
              {monthShort(m.date, lang)}
            </text>
          ))}
        </svg>
      )}
    </ChartFrame>
  )
}
