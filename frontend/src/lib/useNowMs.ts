import { useEffect, useState } from 'react'

/** The time in ms, kept current every `everyMs` while `active`; frozen while not. */
export function useNowMs(everyMs: number, active = true): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!active) return
    setNow(Date.now())
    const timer = window.setInterval(() => setNow(Date.now()), everyMs)
    return () => window.clearInterval(timer)
  }, [everyMs, active])
  return now
}
