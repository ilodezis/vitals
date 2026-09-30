import { useRef, useState, type CSSProperties, type ReactNode, type RefObject } from 'react'
import { useT } from '@/i18n/useT'
import { cx } from '@/lib/cx'
import { weekdayDate } from '@/lib/dates'
import type { ScrubPoint } from './geometry'

interface ChartFrameProps {
  /** The box's own children (the SVG). Drawn at the box's real width. */
  children: ReactNode
  /** Points a finger can land on; leave empty for a chart without a scrub. */
  scrub?: readonly ScrubPoint[]
  /** How a point is read out: the big value line of the tip. */
  readout?: (p: ScrubPoint) => string
  /** The quiet line under it; the point's weekday and date unless told otherwise (a clock time). */
  caption?: (p: ScrubPoint) => string
  className?: string
  style?: CSSProperties
  /** The line-drawing intro; off when a chart is only being redrawn at a new width. */
  intro?: boolean
  /** The caller's ref to the box, when it needs the box's width. */
  boxRef?: RefObject<HTMLDivElement | null>
}

interface Reading {
  point: ScrubPoint
  /** Where the tip sits: under the finger, but never off either edge of the box. */
  tipX: number
}

/** The box every chart sits in: `.chart` styles, the intro draw, and the scrub — hold a finger
 *  (or the pointer) anywhere on the chart to get a rule, a dot and the reading. */
export function ChartFrame({ children, scrub = [], readout, caption, className, style, intro = true, boxRef }: ChartFrameProps) {
  const { lang } = useT()
  const ownRef = useRef<HTMLDivElement>(null)
  const box = boxRef ?? ownRef
  const [reading, setReading] = useState<Reading | null>(null)

  const show = (clientX: number) => {
    const el = box.current
    if (el === null || scrub.length === 0) return
    const r = el.getBoundingClientRect()
    const k = r.width / el.offsetWidth || 1
    const x = (clientX - r.left) / k
    let best = scrub[0] as ScrubPoint
    for (const p of scrub) if (Math.abs(p.x - x) < Math.abs(best.x - x)) best = p
    setReading({ point: best, tipX: Math.min(Math.max(best.x, 70), Math.max(el.offsetWidth - 70, 70)) })
  }
  const hide = () => setReading(null)
  const point = reading?.point

  return (
    <div
      ref={box}
      className={cx('chart', intro && 'intro', reading !== null && 'scrubbing', className)}
      style={style}
      onPointerDown={(e) => show(e.clientX)}
      onPointerMove={(e) => {
        if (e.pointerType === 'mouse' || e.buttons) show(e.clientX)
      }}
      onPointerLeave={hide}
      onPointerUp={hide}
      onPointerCancel={hide}
    >
      {children}
      <div className="scrub" style={{ left: point?.x }} />
      <div className="scrub-dot" style={{ left: point?.x, top: point?.y }} />
      <div className="tip" style={{ left: reading?.tipX }}>
        {point !== undefined && (
          <>
            <b>{readout === undefined ? String(point.value) : readout(point)}</b>
            {caption === undefined ? weekdayDate(point.date, lang) : caption(point)}
          </>
        )}
      </div>
    </div>
  )
}
