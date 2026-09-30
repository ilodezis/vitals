import { useMemo, useRef } from 'react'
import { useT } from '@/i18n/useT'
import { formatCompact } from '@/lib/format'
import { useElementWidth } from '@/lib/useElementWidth'
import { ChartFrame } from './ChartFrame'
import { clockOf, curvesGeometry, type CurveSeriesIn } from './curves'
import type { ScrubPoint } from './geometry'

export interface TimeCurveSeries extends CurveSeriesIn {
  label: string
  color: string
}

interface TimeCurvesProps {
  series: readonly TimeCurveSeries[]
  leftRange?: readonly [number, number]
  /** What the chart shows, for a screen reader. */
  label: string
}

/** Curves on a clock axis — a day's stress and Body Battery, a night's pulse — with their legend.
 *  Hold a finger on it for every series' reading at that minute. */
export function TimeCurves({ series, leftRange, label }: TimeCurvesProps) {
  const { lang } = useT()
  const box = useRef<HTMLDivElement>(null)
  const width = useElementWidth(box)
  const g = useMemo(() => curvesGeometry({ width, series, leftRange }), [width, series, leftRange])
  const present = series.filter((s) => s.points.length > 0)
  const scrub: ScrubPoint[] = g.readings.map((r, i) => ({ x: r.x, y: g.dotY[i] ?? 0, value: i, date: new Date(0) }))
  const readout = (p: ScrubPoint) => {
    const r = g.readings[p.value]
    if (r === undefined) return ''
    return present
      .filter((s) => r.values[s.key] !== undefined)
      .map((s) => `${s.label} ${formatCompact(r.values[s.key] as number, lang)}`)
      .join(' · ')
  }
  const caption = (p: ScrubPoint) => clockOf(g.readings[p.value]?.minute ?? 0)

  return (
    <div>
      <ChartFrame boxRef={box} scrub={scrub} readout={readout} caption={caption}>
        {width > 0 && !g.empty && (
          <svg width={width} height={g.height} role="img" aria-label={label}>
            {g.leftTicks.map((tick) => (
              <g key={`l${tick.value}`}>
                <line className="grid" x1={g.left} x2={g.right} y1={tick.y} y2={tick.y} strokeDasharray="2 4" />
                <text className="ax" x={g.left - 6} y={tick.y + 4} textAnchor="end">
                  {formatCompact(tick.value, lang)}
                </text>
              </g>
            ))}
            {g.rightTicks.map((tick) => (
              <text key={`r${tick.value}`} className="ax" x={g.right + 6} y={tick.y + 4}>
                {formatCompact(tick.value, lang)}
              </text>
            ))}
            {present.map((s) => (
              <path key={s.key} className="draw" pathLength={1} d={g.paths[s.key]} fill="none" stroke={s.color} strokeWidth={1.8} strokeLinecap="round" strokeLinejoin="round" />
            ))}
            {g.xTicks.map((tick) => (
              <text key={tick.label + tick.x} className="ax" x={tick.x} y={g.height - 5} textAnchor="middle">
                {tick.label}
              </text>
            ))}
          </svg>
        )}
      </ChartFrame>
      <div className="legend">
        {present.map((s) => (
          <span key={s.key}>
            <i style={{ background: s.color }} />
            {s.label}
          </span>
        ))}
      </div>
    </div>
  )
}
