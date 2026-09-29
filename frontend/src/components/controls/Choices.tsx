import type { ReactNode } from 'react'
import { cx } from '@/lib/cx'

export interface FilterOption {
  id: string
  label: string
  /** A count printed after the label, in the alarm colour ("Out of range 1"). */
  count?: number
}

/** A row of filters: text, the chosen one on a light capsule. */
export function FilterRow({
  options,
  value,
  onChange,
}: {
  options: readonly FilterOption[]
  value: string
  onChange: (id: string) => void
}) {
  return (
    <div className="filters" role="group">
      {options.map((o) => (
        <button key={o.id} type="button" className={cx('filter', o.id === value && 'on')} aria-pressed={o.id === value} onClick={() => onChange(o.id)}>
          {o.label}
          {o.count !== undefined && <span className="n">{o.count}</span>}
        </button>
      ))}
    </div>
  )
}

export interface Choice {
  id: string
  label: ReactNode
  /** A quiet note inside the capsule ("least often"). */
  hint?: string
}

/** A choice inside a form: the same capsule as the filters, one chosen at a time. */
export function OptionGroup({
  options,
  value,
  onChange,
  label,
}: {
  options: readonly Choice[]
  value: string
  onChange: (id: string) => void
  label?: string
}) {
  return (
    <div className="opts" role="group" aria-label={label}>
      {options.map((o) => (
        <button key={o.id} type="button" className={cx('opt', o.id === value && 'on')} aria-pressed={o.id === value} onClick={() => onChange(o.id)}>
          {o.label}
          {o.hint !== undefined && <span className="hint">{o.hint}</span>}
        </button>
      ))}
    </div>
  )
}
