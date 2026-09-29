import { useLayoutEffect, useRef } from 'react'
import { cx } from '@/lib/cx'

export interface SegmentOption<T extends string> {
  id: T
  label: string
}

interface SegmentedProps<T extends string> {
  options: readonly SegmentOption<T>[]
  value: T
  onChange: (id: T) => void
  className?: string
  label?: string
}

/** A choice on the page: text, the chosen one on a light capsule that slides between them. */
export function Segmented<T extends string>({ options, value, onChange, className, label }: SegmentedProps<T>) {
  const box = useRef<HTMLDivElement>(null)

  useLayoutEffect(() => {
    const el = box.current
    if (el === null) return
    const place = () => {
      const on = el.querySelector<HTMLElement>('button.on')
      const pill = el.querySelector<HTMLElement>('.pill')
      if (on === null || pill === null) return
      pill.style.width = `${on.offsetWidth}px`
      pill.style.transform = `translateX(${on.offsetLeft}px)`
    }
    place()
    const observer = new ResizeObserver(place)
    observer.observe(el)
    return () => observer.disconnect()
  }, [value, options])

  return (
    <div ref={box} className={cx('seg', className)} role="group" aria-label={label}>
      <i className="pill" />
      {options.map((o) => (
        <button key={o.id} type="button" className={o.id === value ? 'on' : undefined} aria-pressed={o.id === value} onClick={() => onChange(o.id)}>
          {o.label}
        </button>
      ))}
    </div>
  )
}
