import type { ElementType, ReactNode } from 'react'
import { Icon, type IconName } from '@/components/icons/Icon'
import { cx } from '@/lib/cx'

/** The ladder: an observation, a heads-up, a warning, a stop that asks before it lets go. */
export type AlertTone = 'note' | 'info' | 'warn' | 'block'

const DEFAULT_ICON: Record<AlertTone, IconName> = {
  note: 'eye',
  info: 'info',
  warn: 'warn',
  block: 'block',
}

type AlertProps<T extends ElementType> = {
  tone?: AlertTone
  icon?: IconName
  /** The small line under the message: where the finding came from. */
  evidence?: ReactNode
  /** Actions under the message ("Fix it", "Save anyway"). */
  actions?: ReactNode
  /** Lets the reader put the alert away: a small cross at the right, named by `dismissLabel`. */
  onDismiss?: () => void
  dismissLabel?: string
  children: ReactNode
  /** Render as something else, e.g. a link that opens the screen the finding is about. */
  as?: T
  className?: string
} & Omit<React.ComponentPropsWithoutRef<T>, 'as' | 'children' | 'className'>

export function Alert<T extends ElementType = 'div'>({
  tone = 'note',
  icon,
  evidence,
  actions,
  onDismiss,
  dismissLabel,
  children,
  as,
  className,
  ...rest
}: AlertProps<T>) {
  const Tag: ElementType = as ?? 'div'
  return (
    <Tag className={cx('alert', tone !== 'note' && tone, onDismiss !== undefined && 'has-x', className)} {...rest}>
      <Icon name={icon ?? DEFAULT_ICON[tone]} />
      <div>
        {children}
        {evidence !== undefined && <span className="ev">{evidence}</span>}
        {actions !== undefined && <div className="acts">{actions}</div>}
      </div>
      {onDismiss !== undefined && (
        <button type="button" className="alert-x" aria-label={dismissLabel} title={dismissLabel} onClick={onDismiss}>
          <Icon name="x" />
        </button>
      )}
    </Tag>
  )
}
