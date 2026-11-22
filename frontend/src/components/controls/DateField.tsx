import type { FocusEvent, MouseEvent, Ref } from 'react'
import { useToday } from '@/app/session'
import { useT } from '@/i18n/useT'
import { cx } from '@/lib/cx'
import { fieldDate, parseIsoDate } from '@/lib/dates'

interface DateFieldProps {
  /** ISO date, or '' for none. */
  value: string
  onChange: (iso: string) => void
  id?: string
  name?: string
  min?: string
  max?: string
  placeholder?: string
  invalid?: boolean
  describedBy?: string
  inputRef?: Ref<HTMLInputElement>
  onBlur?: (e: FocusEvent<HTMLInputElement>) => void
}

/** A date drawn like every other input, in the app's language. The native date input lies over it
 *  unseen and only opens the system picker: drawn by itself on iOS it ignores box-sizing, runs past
 *  its column and writes the date in the device's language. */
export function DateField({
  value,
  onChange,
  id,
  name,
  min,
  max,
  placeholder = '',
  invalid = false,
  describedBy,
  inputRef,
  onBlur,
}: DateFieldProps) {
  const { lang } = useT()
  const today = useToday()
  // A click on the hidden field's text would only focus it on a desktop: open the picker instead.
  const openPicker = (e: MouseEvent<HTMLInputElement>) => {
    try {
      e.currentTarget.showPicker?.()
    } catch {
      /* not allowed here: the field still takes typing */
    }
  }
  return (
    <span className={cx('input datef', invalid && 'invalid')}>
      <span className="datef-v">{value === '' ? placeholder : fieldDate(parseIsoDate(value), today, lang)}</span>
      <input
        ref={inputRef}
        id={id}
        className="datef-i"
        type="date"
        name={name}
        value={value}
        min={min}
        max={max}
        aria-invalid={invalid || undefined}
        aria-describedby={describedBy}
        onClick={openPicker}
        onBlur={onBlur}
        onChange={(e) => onChange(e.target.value)}
      />
    </span>
  )
}
