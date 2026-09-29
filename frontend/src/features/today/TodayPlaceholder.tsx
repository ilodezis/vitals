import { Icon } from '@/components/icons/Icon'
import './placeholder.css'

/** Stands in for the Today screen until it is built: proves the fonts, tokens and icons load. */
export function TodayPlaceholder() {
  return (
    <main className="scaffold">
      <Icon name="today" className="scaffold-icon" />
      <h1 className="scaffold-mark">Vitals</h1>
    </main>
  )
}
