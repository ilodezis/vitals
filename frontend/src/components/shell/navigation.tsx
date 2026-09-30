import { useCallback, type AnchorHTMLAttributes, type MouseEvent } from 'react'
import { useRouter } from '@tanstack/react-router'
import { announceNavigation } from './navIntent'
import { SCREEN_PATH, type ScreenId } from './nav'
import type { NavMode } from './stack'
import { preloadScreen } from './screens'

/** The address a screen lives at — for a link's `href`. */
export const hrefOf = (screen: ScreenId): string => SCREEN_PATH[screen]

const SCROLL_TOP = 'vitals:scroll-top'

/** Ask the stage to scroll its current screen to the top (a tap on where you already are). */
export function scrollCurrentToTop(): void {
  window.dispatchEvent(new Event(SCROLL_TOP))
}
export const SCROLL_TOP_EVENT = SCROLL_TOP

/** Go to a screen. `mode` says how it should feel: `push` slides in deeper, `replace` swaps the
 *  current one for a sibling (a section tab), `tab` starts over. */
export function useGo() {
  const router = useRouter()
  return useCallback(
    (screen: ScreenId, options: { mode?: NavMode; shared?: HTMLElement | null } = {}) => {
      const mode = options.mode ?? 'push'
      if (router.state.location.pathname === SCREEN_PATH[screen]) {
        scrollCurrentToTop()
        return
      }
      announceNavigation({ mode, shared: options.shared })
      // The route tree is generated from the files; the address is plain data here.
      void router.navigate({ to: SCREEN_PATH[screen] as never, replace: mode === 'replace' })
    },
    [router],
  )
}

/** The browser's own back, so the address and the stack stay one thing. `steps` goes further. */
export function useBack() {
  const router = useRouter()
  return useCallback((steps = 1) => router.history.go(-steps), [router])
}

type ScreenLinkProps = {
  screen: ScreenId
  mode?: NavMode
  /** Fly the weight figure inside this link to the next screen's hero. */
  sharedFigure?: boolean
} & Omit<AnchorHTMLAttributes<HTMLAnchorElement>, 'href'>

/** A link to a screen: a real anchor (open in a new tab works), driven by the app's motion. */
export function ScreenLink({ screen, mode, sharedFigure = false, onClick, onPointerEnter, onFocus, children, ...rest }: ScreenLinkProps) {
  const go = useGo()
  return (
    <a
      href={hrefOf(screen)}
      {...rest}
      onClick={(e: MouseEvent<HTMLAnchorElement>) => {
        onClick?.(e)
        if (e.defaultPrevented || e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return
        e.preventDefault()
        const shared = sharedFigure ? e.currentTarget.querySelector<HTMLElement>('[data-fig]') : null
        go(screen, { mode, shared })
      }}
      onPointerEnter={(e) => {
        onPointerEnter?.(e)
        preloadScreen(screen)
      }}
      onFocus={(e) => {
        onFocus?.(e)
        preloadScreen(screen)
      }}
    >
      {children}
    </a>
  )
}
