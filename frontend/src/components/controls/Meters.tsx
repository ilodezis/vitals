import { cx } from '@/lib/cx'
import { percentOf, rangeBarLayout } from './gauges'

/** Progress to a goal: a bar that fills, with optional ticks and a marked zone. */
export function Meter({
  value,
  tone,
  ticks = [],
  zone,
}: {
  /** 0–100. */
  value: number
  tone?: 'warn' | 'bad'
  ticks?: readonly number[]
  zone?: readonly [number, number]
}) {
  return (
    <div className={cx('meter', tone)} role="progressbar" aria-valuenow={Math.round(value)} aria-valuemin={0} aria-valuemax={100}>
      <i style={{ width: `${percentOf(value, 0, 100)}%` }} />
      {zone !== undefined && <span className="zone" style={{ left: `${zone[0]}%`, width: `${zone[1] - zone[0]}%` }} />}
      {ticks.map((tick) => (
        <span key={tick} className="tick" style={{ left: `${tick}%` }} />
      ))}
    </div>
  )
}

/** A value on the corridor of its norm, with where it was a week ago when that matters. */
export function RangeBar({
  value,
  lo,
  hi,
  min,
  max,
  prev,
  tone,
}: {
  value: number
  /** The corridor; left out for a metric that has none. */
  lo?: number | null
  hi?: number | null
  min: number
  max: number
  prev?: number
  tone?: 'good' | 'bad' | 'warn' | ''
}) {
  const layout = rangeBarLayout({ value, lo, hi, min, max, prev })
  const stretch = tone === 'good' ? 'var(--good)' : tone === 'bad' ? 'var(--bad-strong)' : 'var(--muted)'
  return (
    <div className="rbar">
      <span className="track" />
      {layout.ref !== null && <span className="ref" style={{ left: `${layout.ref.left}%`, width: `${layout.ref.width}%` }} />}
      {layout.move !== null && (
        <>
          <span className="con" style={{ left: `${layout.move.left}%`, width: `${layout.move.width}%`, background: stretch, opacity: 0.55 }} />
          <span className="prev" style={{ left: `${layout.move.from}%` }} />
        </>
      )}
      <span className={cx('pt', tone)} style={{ left: `${layout.point}%` }} />
    </div>
  )
}
