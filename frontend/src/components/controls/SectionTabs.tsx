import { useLayoutEffect, useRef } from 'react'
import { useLayout } from '@/components/shell/layout'
import { cx } from '@/lib/cx'

export interface TabItem {
  id: string
  label: string
  /** The real address, so the tab is a link a right-click or a long-press understands. */
  href?: string
}

interface SectionTabsProps {
  items: readonly TabItem[]
  active: string | null
  onSelect: (id: string) => void
  /** Called on hover / focus so the next screen can be fetched before the tap. */
  onPreload?: (id: string) => void
  /** The second level of "where you are": the same underline, a step quieter. */
  sub?: boolean
}

/** "Where you are": text with an amber underline that slides to the active tab. */
export function SectionTabs({ items, active, onSelect, onPreload, sub = false }: SectionTabsProps) {
  const nav = useRef<HTMLElement>(null)
  const { desktop } = useLayout()

  useLayoutEffect(() => {
    const el = nav.current
    if (el === null) return
    const place = () => {
      const on = el.querySelector<HTMLElement>('.chip.on')
      const ink = el.querySelector<HTMLElement>('.ink')
      if (on === null || ink === null) return
      ink.style.transform = `translateX(${on.offsetLeft}px) scaleX(${on.offsetWidth / 100})`
      // On a phone the row scrolls: keep the active tab in view.
      if (!desktop) el.scrollLeft = on.offsetLeft + on.offsetWidth > el.clientWidth - 20 ? on.offsetLeft - 20 : 0
    }
    place()
    const observer = new ResizeObserver(place)
    observer.observe(el)
    return () => observer.disconnect()
  }, [active, desktop, items])

  return (
    <nav ref={nav} className={cx('chips', sub && 'sub')}>
      {items.map((item) => (
        <a
          key={item.id}
          href={item.href ?? '#'}
          className={cx('chip', item.id === active && 'on')}
          aria-current={item.id === active ? 'page' : undefined}
          onClick={(e) => {
            if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return
            e.preventDefault()
            onSelect(item.id)
          }}
          onPointerEnter={() => onPreload?.(item.id)}
          onFocus={() => onPreload?.(item.id)}
        >
          {item.label}
        </a>
      ))}
      <i className="ink" />
    </nav>
  )
}
