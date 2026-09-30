import type { ReactNode } from 'react'
import { Icon } from '@/components/icons/Icon'
import { cx } from '@/lib/cx'

interface DisclosureProps {
  open: boolean
  onToggle: () => void
  title: ReactNode
  /** A quiet line under the title. */
  sub?: ReactNode
  /** How many things are inside, on the right. */
  count?: ReactNode
  /** Actions of the row itself (delete…): next to the header, never inside its button. */
  actions?: ReactNode
  className?: string
  /** Drawn only while open. */
  children: ReactNode
}

/** A list that opens on a tap: a small arrow, the name, the count on the right. The one
 *  collapsible header of the app — the arrow's size is set here, not by whoever uses it. */
export function Disclosure({ open, onToggle, title, sub, count, actions, className, children }: DisclosureProps) {
  return (
    <div className={cx('disc', open && 'open', className)}>
      <div className="disc-h">
        <button type="button" className="disc-b" aria-expanded={open} onClick={onToggle}>
          <Icon name="chevR" className="disc-chev" />
          <span className="disc-t">
            {title}
            {sub !== undefined && <small>{sub}</small>}
          </span>
          {count !== undefined && <span className="disc-n num">{count}</span>}
        </button>
        {actions}
      </div>
      {open && children}
    </div>
  )
}
