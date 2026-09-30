import { useEffect, useState } from 'react'
import { Icon, type IconName } from '@/components/icons/Icon'
import { useT } from '@/i18n/useT'
import { cx } from '@/lib/cx'
import { TextButton } from './Marks'

/** How long a first press stays armed before the button goes back to what it was. */
const DISARM_MS = 4000

/** The first press asks, the second one does it. */
export function pressConfirm(armed: boolean): { armed: boolean; fire: boolean } {
  return armed ? { armed: false, fire: true } : { armed: true, fire: false }
}

interface ConfirmButtonProps {
  /** What the button does, for a screen reader and the tooltip ("Delete"). */
  label: string
  onConfirm: () => void
  icon?: IconName
  /** Draw the label next to the icon: a text action instead of a row's icon. */
  text?: boolean
  disabled?: boolean
  className?: string
}

/** An action that cannot be taken back (a delete without an Undo): it asks first. The first
 *  press turns the button into the question, a second one within a few seconds confirms it;
 *  looking away — focus moving on, the time running out — leaves everything as it was. */
export function ConfirmButton({ label, onConfirm, icon = 'trash', text = false, disabled = false, className }: ConfirmButtonProps) {
  const { t } = useT()
  const [armed, setArmed] = useState(false)

  useEffect(() => {
    if (!armed) return
    const timer = window.setTimeout(() => setArmed(false), DISARM_MS)
    return () => window.clearTimeout(timer)
  }, [armed])

  const press = () => {
    const step = pressConfirm(armed)
    setArmed(step.armed)
    if (step.fire) onConfirm()
  }
  const question = t('common.confirm_question')

  if (text) {
    return (
      <TextButton icon={armed ? 'warn' : icon} danger={armed} disabled={disabled} className={className} onClick={press} onBlur={() => setArmed(false)}>
        {armed ? question : label}
      </TextButton>
    )
  }
  return (
    <button
      type="button"
      className={cx('ibtn', 'danger', armed && 'armed', className)}
      aria-label={armed ? `${label}: ${question}` : label}
      title={armed ? question : label}
      disabled={disabled}
      onClick={press}
      onBlur={() => setArmed(false)}
    >
      <Icon name={armed ? 'warn' : icon} />
    </button>
  )
}
