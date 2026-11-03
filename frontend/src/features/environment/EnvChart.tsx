import { useId, useMemo, useRef } from 'react'
import { ChartFrame } from '@/components/charts/ChartFrame'
import type { ScrubPoint } from '@/components/charts/geometry'
import { useT } from '@/i18n/useT'
import { clockLabel, weekdayShort } from '@/lib/dates'
import { formatCompact } from '@/lib/format'
import { useElementWidth } from '@/lib/useElementWidth'
import { chartGeometry, type ChartReading } from './chart'
import { COLOR, zoneStops, type ChartModel } from './model'
import type { EnvThresholds } from './types'

/** How a curve is named, coloured and read out. */
export interface CurveStyle {
  color: string
  /** The legend's entry, unit included. */
  label: string
  /** The curve's name in the reading under a finger, where the unit follows the number. */
  name: string
  unit: string
  digits: number
  /** Whether to draw a quiet subtle gradient area under the curve. */
  area?: boolean
  /** Line width in pixels (defaults to 1.8). */
  strokeWidth?: number
}

interface EnvChartProps {
  model: ChartModel
  start: number
  end: number
  /** What the chart shows, for a screen reader. */
  label: string
  styles: Record<string, CurveStyle>
  /** What each threshold rule is called in the legend, by rule key; rules sharing a name share an entry. */
  ruleLabels?: Record<string, string>
  /** What the band behind the curve (an hour's range) is called. */
  bandLabel?: string
  /** Draw the first curve in the colour of the CO₂ zone it is in. */
  zones?: EnvThresholds
  /** Room for the left scale: a chart under the hypnogram uses the hypnogram's. */
  left?: number
  /** The clock labels, when they have to line up with another chart's. */
  ticks?: readonly number[]
  height?: number
}

const SPAN_WITH_DAYS_MS = 30 * 3_600_000

const tickDigits = (ticks: readonly { value: number }[]): number =>
  ticks.some((t) => Math.abs(t.value - Math.round(t.value)) > 1e-4) ? 1 : 0

/** The station's curves on a clock, with the thresholds as rules. Hold a finger on it for the
 *  readings of that moment. */
export function EnvChart({ model, start, end, label, styles, ruleLabels = {}, bandLabel, zones, left, ticks, height }: EnvChartProps) {
  const { lang } = useT()
  const box = useRef<HTMLDivElement>(null)
  const width = useElementWidth(box)
  const gradientId = useId()
  const g = useMemo(
    () =>
      chartGeometry({
        width,
        height,
        start,
        end,
        lines: model.lines,
        rules: model.rules,
        band: model.band,
        include: model.include,
        minSpan: model.minSpan,
        gapMs: model.gapMs,
        left,
        ticks,
      }),
    [width, height, start, end, model, left, ticks],
  )
  const withDays = end - start > SPAN_WITH_DAYS_MS
  const num = (v: number, digits: number) => formatCompact(v, lang, digits)
  const leftDigits = tickDigits(g.leftTicks)
  const rightDigits = tickDigits(g.rightTicks)

  const scrub: ScrubPoint[] = g.readings.map((r, i) => ({ x: r.x, y: g.dotY[i] ?? 0, value: i, date: new Date(r.t) }))
  const readout = (p: ScrubPoint) => {
    const r: ChartReading | undefined = g.readings[p.value]
    if (r === undefined) return ''
    return model.lines
      .filter((l) => r.values[l.key] !== undefined)
      .map((l) => {
        const s = styles[l.key]
        return s === undefined ? '' : `${s.name} ${num(r.values[l.key] as number, s.digits)}${s.unit === '' ? '' : ` ${s.unit}`}`
      })
      .join(' · ')
  }
  const caption = (p: ScrubPoint) => {
    const at = new Date(g.readings[p.value]?.t ?? 0)
    return withDays ? `${weekdayShort(at, lang)} ${clockLabel(at)}` : clockLabel(at)
  }

  const first = model.lines[0]
  const zoned = zones !== undefined && first !== undefined && !g.empty
  const stroke = (key: string) => (zoned && key === first?.key ? `url(#${gradientId})` : (styles[key]?.color ?? COLOR.neutral))

  const present = model.lines.filter((l) => l.points.length > 0)
  const legendRules: { label: string; rule: string }[] = []
  for (const rule of g.rules) {
    const name = ruleLabels[rule.key]
    if (name !== undefined && !legendRules.some((r) => r.label === name)) legendRules.push({ label: name, rule: rule.key })
  }

  return (
    <div className="env-chart-box">
      <ChartFrame boxRef={box} scrub={scrub} readout={readout} caption={caption} className="env-chart" intro={false}>
      {width > 0 && !g.empty && (
        <svg width={width} height={g.height} role="img" aria-label={label}>
          <defs>
            {zoned && (
              <>
                <linearGradient id={gradientId} gradientUnits="userSpaceOnUse" x1="0" x2="0" y1={g.top} y2={g.bottom}>
                  {zoneStops(g, zones).map((s, i) => (
                    <stop key={i} offset={s.offset} style={{ stopColor: s.color }} />
                  ))}
                </linearGradient>
                <linearGradient id={`${gradientId}-area`} gradientUnits="userSpaceOnUse" x1="0" x2="0" y1={g.top} y2={g.bottom}>
                  {zoneStops(g, zones).map((s, i) => (
                    <stop key={i} offset={s.offset} stopColor={s.color} stopOpacity={0.12 * (1 - s.offset * 0.75)} />
                  ))}
                </linearGradient>
              </>
            )}
            {model.lines.map((l) => (
              <linearGradient key={`grad-${l.key}`} id={`${gradientId}-area-${l.key}`} x1="0" x2="0" y1="0" y2="1">
                <stop offset="0%" stopColor={styles[l.key]?.color ?? COLOR.neutral} stopOpacity="0.10" />
                <stop offset="100%" stopColor={styles[l.key]?.color ?? COLOR.neutral} stopOpacity="0" />
              </linearGradient>
            ))}
          </defs>
          {model.lines.map((l) => {
            const showArea = styles[l.key]?.area ?? (model.lines.length === 1)
            const areaD = g.areas[l.key]
            if (!showArea || !areaD) return null
            const fillUrl = zoned && l.key === first?.key ? `url(#${gradientId}-area)` : `url(#${gradientId}-area-${l.key})`
            return <path key={`area-${l.key}`} d={areaD} fill={fillUrl} />
          })}
          {g.leftTicks.map((tick) => (
            <g key={`l${tick.value}`}>
              <line className="grid" x1={g.left} x2={g.right} y1={tick.y} y2={tick.y} strokeDasharray="2 4" />
              <text className="ax" x={g.left - 6} y={tick.y + 4} textAnchor="end">
                {num(tick.value, leftDigits)}
              </text>
            </g>
          ))}
          {g.rightTicks.map((tick) => (
            <text key={`r${tick.value}`} className="ax" x={g.right + 6} y={tick.y + 4}>
              {num(tick.value, rightDigits)}
            </text>
          ))}
          {g.xTicks.map((tick) => {
            const at = new Date(tick.t)
            const midnight = withDays && at.getHours() === 0 && at.getMinutes() === 0
            return (
              <g key={tick.t}>
                {midnight && <line className="env-day" x1={tick.x} x2={tick.x} y1={g.top} y2={g.bottom} />}
                <text className="ax" x={tick.x} y={g.height - 5} textAnchor="middle">
                  {midnight ? weekdayShort(at, lang) : clockLabel(at)}
                </text>
              </g>
            )
          })}
          {g.band !== '' && <path d={g.band} fill={COLOR.co2} fillOpacity={0.14} />}
          {g.rules.map((rule) => (
            <g key={rule.key} className="env-rule" data-rule={rule.key}>
              <line x1={g.left} x2={g.right} y1={rule.y} y2={rule.y} strokeDasharray="5 4" />
              <text className="ax" x={g.right - 2} y={rule.y - 4} textAnchor="end">
                {num(rule.value, rule.value % 1 === 0 ? 0 : 1)}
              </text>
            </g>
          ))}
          {model.lines.map((l) => (
            <path key={l.key} d={g.paths[l.key]} fill="none" stroke={stroke(l.key)} strokeWidth={styles[l.key]?.strokeWidth ?? 1.8} strokeLinecap="round" strokeLinejoin="round" />
          ))}
        </svg>
      )}
      </ChartFrame>
      <div className="legend">
        {present.map((l) => (
          <span key={l.key}>
            <i style={{ background: styles[l.key]?.color ?? COLOR.neutral }} />
            {styles[l.key]?.label}
          </span>
        ))}
        {g.band !== '' && bandLabel !== undefined && (
          <span>
            <i className="env-lg-band" />
            {bandLabel}
          </span>
        )}
        {legendRules.map((r) => (
          <span key={r.label} data-rule={r.rule}>
            <i className="env-lg-rule" />
            {r.label}
          </span>
        ))}
      </div>
    </div>
  )
}
