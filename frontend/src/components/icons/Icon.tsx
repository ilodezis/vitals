import { ICONS, type IconName } from './paths'
import './icon.css'

export type { IconName }

type IconProps = {
  name: IconName
  className?: string
}

/** One icon from the Vitals family. Decorative: the label next to it carries the meaning. */
export function Icon({ name, className }: IconProps) {
  return (
    <svg
      className={className === undefined ? 'icon' : `icon ${className}`}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.6}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      // Static markup from our own dictionary, never user data.
      dangerouslySetInnerHTML={{ __html: ICONS[name] }}
    />
  )
}
