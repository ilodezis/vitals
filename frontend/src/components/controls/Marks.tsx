import type { ButtonHTMLAttributes, ReactNode } from 'react'
import { Icon, type IconName } from '@/components/icons/Icon'
import { cx } from '@/lib/cx'

export type Tone = 'good' | 'bad' | 'cool' | 'violet' | 'warn' | 'deep' | 'plain'

/** Provenance or a tag: a coloured dot and muted text, never a plaque. */
export function Badge({ tone, children, className }: { tone?: Tone; children: ReactNode; className?: string }) {
  return <span className={cx('badge', tone, className)}>{children}</span>
}

/** A change with its direction: an arrow, a number, coloured only when it is better or worse. */
export function Delta({
  tone,
  icon,
  children,
  className,
}: {
  tone?: 'good' | 'bad'
  icon?: IconName
  children: ReactNode
  className?: string
}) {
  return (
    <span className={cx('delta', tone, className)}>
      {icon !== undefined && <Icon name={icon} />}
      {children}
    </span>
  )
}

interface TextButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  icon?: IconName
  danger?: boolean
  spinning?: boolean
}

/** A secondary action: text with an icon; a surface only on hover. */
export function TextButton({ icon, danger = false, spinning = false, className, children, type = 'button', ...rest }: TextButtonProps) {
  return (
    <button type={type} className={cx('ghost', danger && 'danger', spinning && 'spin', className)} {...rest}>
      {icon !== undefined && <Icon name={icon} />}
      {children}
    </button>
  )
}

/** A coloured dot: the source of a row, the kind of a feed entry. */
export function Dot({ tone }: { tone?: 'good' | 'cool' | 'violet' | 'accent' | 'bad' }) {
  return <i className={cx('dot', tone)} />
}
