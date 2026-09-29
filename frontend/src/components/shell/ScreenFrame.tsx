import { createContext, use, useLayoutEffect, useRef, type ReactNode } from 'react'
import type { ScreenId } from './nav'

/** What a screen needs to know about where it sits in the stack. */
export interface ScreenInfo {
  id: ScreenId
  /** The screen "back" returns to; null on the first screen of a stack. */
  back: ScreenId | null
  /** True for the very first screen of a visit: Today's sentence and figures arrive with a flourish. */
  firstVisit: boolean
}

const ScreenContext = createContext<ScreenInfo | null>(null)

export function ScreenProvider({ info, children }: { info: ScreenInfo; children: ReactNode }) {
  return <ScreenContext value={info}>{children}</ScreenContext>
}

export function useScreen(): ScreenInfo {
  const info = use(ScreenContext)
  if (info === null) throw new Error('useScreen() must be used inside a screen')
  return info
}

/** How far a screen has scrolled, as 0–1 over a 40px run after the first 24px: the large title
 *  hands over to the compact bar in the same stretch. */
export function scrollProgress(scrollTop: number): number {
  return Math.min(1, Math.max(0, (scrollTop - 24) / 40))
}

interface ScreenFrameProps {
  id: ScreenId
  hidden: boolean
  register: (node: HTMLElement | null) => void
  children: ReactNode
}

/** One screen in the stack: its own scroller, its own scroll position kept while another
 *  screen is on top, and the scroll progress the title bar reads (`--p`). */
export function ScreenFrame({ id, hidden, register, children }: ScreenFrameProps) {
  const node = useRef<HTMLElement | null>(null)
  const saved = useRef(0)

  // A hidden screen has no layout, so its scroll position is put back when it returns.
  useLayoutEffect(() => {
    if (!hidden && node.current !== null) node.current.scrollTop = saved.current
  }, [hidden])

  return (
    <section
      ref={(el) => {
        node.current = el
        register(el)
        return () => register(null)
      }}
      className="screen"
      data-screen={id}
      hidden={hidden}
      onScroll={(e) => {
        const el = e.currentTarget
        saved.current = el.scrollTop
        el.style.setProperty('--p', scrollProgress(el.scrollTop).toFixed(3))
      }}
    >
      <div className="page">{children}</div>
    </section>
  )
}
