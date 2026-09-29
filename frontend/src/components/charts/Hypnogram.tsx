import { useMemo, useRef } from 'react'
import { useT } from '@/i18n/useT'
import { useElementWidth } from '@/lib/useElementWidth'
import { ChartFrame } from './ChartFrame'
import { hypnogramGeometry } from './geometry'

/** Stage colours, index = the stage code (0 awake, 1 REM, 2 light, 3 deep). */
export const STAGE_COLOR = ['var(--bad)', 'var(--violet)', 'var(--cool)', 'var(--deep)'] as const

const clock = (minutes: number): string =>
  `${String(Math.floor(minutes / 60) % 24).padStart(2, '0')}:${String(minutes % 60).padStart(2, '0')}`

interface HypnogramProps {
  /** Stage per 5-minute block. */
  stages: readonly number[]
  /** Lights out, minutes since midnight. */
  startMinutes: number
}

/** A night as steps: the stage in rows, awake at the top and deep sleep at the bottom. */
export function Hypnogram({ stages, startMinutes }: HypnogramProps) {
  const { t } = useT()
  const box = useRef<HTMLDivElement>(null)
  const width = useElementWidth(box)
  const g = useMemo(() => hypnogramGeometry(width, stages, startMinutes), [width, stages, startMinutes])
  const labels = [t('app.stage.awake_short'), t('app.stage.rem'), t('app.stage.light'), t('app.stage.deep')]

  return (
    <ChartFrame boxRef={box}>
      {width > 0 && (
        <svg width={width} height={g.height} role="img" aria-label={t('app.chart.hypnogram')}>
          {g.rows.map((row, i) => (
            <g key={row.stage}>
              <text className="ax" x={0} y={row.labelY}>
                {labels[i]}
              </text>
              <line className="grid" x1={g.left} x2={width} y1={row.lineY} y2={row.lineY} strokeDasharray="2 4" />
            </g>
          ))}
          <path className="draw" pathLength={1} d={g.outline} fill="none" stroke="#F4F0F6" strokeOpacity=".28" strokeWidth={1} />
          <g className="late">
            {g.blocks.map((b, i) => (
              <rect
                key={i}
                x={b.x.toFixed(1)}
                y={b.y.toFixed(1)}
                width={b.width.toFixed(1)}
                height={b.height.toFixed(1)}
                rx={3}
                fill={STAGE_COLOR[b.stage]}
                fillOpacity={b.stage === 3 ? 0.95 : 0.8}
              />
            ))}
          </g>
          {g.ticks.map((tick) => (
            <text key={tick.minutes} className="ax" x={tick.x} y={g.height - 5} textAnchor="middle">
              {clock(tick.minutes)}
            </text>
          ))}
        </svg>
      )}
    </ChartFrame>
  )
}
