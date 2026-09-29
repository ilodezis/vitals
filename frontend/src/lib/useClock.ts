import { useEffect, useState } from 'react'
import { clockLabel } from './dates'

/** The time of day, "08:05", kept current: it changes on the minute, not every second. */
export function useClock(): string {
  const [label, setLabel] = useState(() => clockLabel(new Date()))
  useEffect(() => {
    let timer = 0
    const tick = () => {
      const now = new Date()
      setLabel(clockLabel(now))
      // Wake up just after the next minute begins.
      timer = window.setTimeout(tick, (60 - now.getSeconds()) * 1000 - now.getMilliseconds() + 20)
    }
    tick()
    return () => window.clearTimeout(timer)
  }, [])
  return label
}
