import type { MouseEvent } from 'react'
import { useToday } from '@/app/session'
import { useT } from '@/i18n/useT'
import { fieldDate, parseIsoDate } from '@/lib/dates'

interface DateFieldProps {
  /** ISO date, or '' for none. */
  value: string
  onChange: (iso: string) => void
  name?: string
  min?: string
  max?: string
}

/** A date drawn like every other input, in the app's language. The native date input lies over it
 *  unseen and only opens the system picker: drawn by itself on iOS it ignores box-sizing, runs past
 *  its column and writes the date in the device's language. */
export function DateField({ value, onChange, name, min, max }: DateFieldProps) {
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
    <span className="input datef">
      <span className="datef-v">{value === '' ? '' : fieldDate(parseIsoDate(value), today, lang)}</span>
      <input
        className="datef-i"
        type="date"
        name={name}
        value={value}
        min={min}
        max={max}
        onClick={openPicker}
        onChange={(e) => onChange(e.target.value)}
      />
    </span>
  )
}
