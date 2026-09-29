import { useLayoutEffect, useState, type RefObject } from 'react'

/** The width of an element, kept current. 0 until it has been measured. Charts are drawn
 *  at the real pixel width of their box, so they ask. */
export function useElementWidth(ref: RefObject<HTMLElement | null>): number {
  const [width, setWidth] = useState(0)
  useLayoutEffect(() => {
    const el = ref.current
    if (el === null) return
    const read = () => setWidth(el.clientWidth)
    read()
    const observer = new ResizeObserver(read)
    observer.observe(el)
    return () => observer.disconnect()
  }, [ref])
  return width
}
