import type { ReactNode } from 'react'
import { cx } from '@/lib/cx'

/** A section heading with its quiet meta on the right. A string meta becomes the muted
 *  caption; anything else (a link) is drawn as given. */
export function SectionHead({ title, meta }: { title: string; meta?: ReactNode }) {
  return (
    <div className="sec-h">
      <h2>{title}</h2>
      {typeof meta === 'string' ? <span className="meta">{meta}</span> : meta}
    </div>
  )
}

export function Section({
  title,
  meta,
  className,
  children,
}: {
  title?: string
  meta?: ReactNode
  className?: string
  children: ReactNode
}) {
  return (
    <section className={cx('sec', className)}>
      {title !== undefined && <SectionHead title={title} meta={meta} />}
      {children}
    </section>
  )
}

/** The value, its unit, its name and a line under it — the inside of a figure. */
export function FigureBody({
  value,
  unit,
  label,
  sub,
  tone,
  subBad = tone === 'bad',
}: {
  value: ReactNode
  unit?: string
  label: ReactNode
  sub?: ReactNode
  tone?: 'good' | 'bad'
  /** The line under a bad value is red too, unless the line only names it. */
  subBad?: boolean
}) {
  return (
    <>
      <div className={cx('f-v', tone)}>
        {value}
        {unit !== undefined && unit !== '' && <span className="u">{unit}</span>}
      </div>
      <div className="f-l">{label}</div>
      {sub !== undefined && <div className={cx('f-s', subBad && 'bad')}>{sub}</div>}
    </>
  )
}
