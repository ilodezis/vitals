import { useEffect, useState, type RefObject } from 'react'

/** Whether an element is on screen. A screen that is not the current one is hidden by the stage, so
 *  this is also "is the person looking at it": a poll that only matters then can switch itself off. */
export function useOnScreen(ref: RefObject<HTMLElement | null>): boolean {
  const [onScreen, setOnScreen] = useState(true)
  useEffect(() => {
    const el = ref.current
    if (el === null || typeof IntersectionObserver === 'undefined') return
    const observer = new IntersectionObserver((entries) => {
      const last = entries[entries.length - 1]
      if (last !== undefined) setOnScreen(last.isIntersecting)
    })
    observer.observe(el)
    return () => observer.disconnect()
  }, [ref])
  return onScreen
}
