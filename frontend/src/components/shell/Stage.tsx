import { Suspense, useEffect, useEffectEvent, useLayoutEffect, useRef, useState } from 'react'
import { useRouter, useRouterState } from '@tanstack/react-router'
import { animate, prefersReducedMotion, settle } from '@/lib/motion'
import { useLayout } from './layout'
import { SCROLL_TOP_EVENT } from './navigation'
import { screenForPath, type ScreenId } from './nav'
import { takeNavigationIntent } from './navIntent'
import { screenComponent } from './screens'
import { ScreenBoundary } from './ScreenBoundary'
import { ScreenFrame, ScreenProvider } from './ScreenFrame'
import { initialStack, planGo, planPop, topOf, type NavPlan, type StackEntry, type StackState } from './stack'
import { fade, sharedMorph, slide, swipeCommits, swipeFrame, whenPresent } from './stageMotion'

/** What is mounted right now: the stack itself, plus screens that are leaving and still
 *  drawn until their motion is over; `moving` are the two the motion is running on. */
interface StageView {
  logical: StackState
  leaving: StackEntry[]
  moving: number[]
}

interface Job {
  plan: NavPlan
  shared: HTMLElement | null
}

interface Swipe {
  pointer: number
  x0: number
  t0: number
  top: HTMLElement
  under: HTMLElement
  width: number
  dx: number
}

/** What the frame around the stage needs: which screen is on top, which one the stack started
 *  with (the bottom bar's lit tab) and how deep it is. */
export interface StackInfo {
  root: ScreenId
  top: ScreenId
  depth: number
}

/** Pointer travel from the left edge that starts a swipe back, in pixels. */
const EDGE = 28

/** The screens, and how they hand over. The router owns the address; this owns the stack: a
 *  change of address becomes a plan (`planGo`) and the plan becomes a motion. A phone keeps the
 *  screens you came through mounted underneath; a desktop shows one. */
export function Stage({ onStack }: { onStack: (info: StackInfo) => void }) {
  const router = useRouter()
  const pathname = useRouterState({ select: (s) => s.location.pathname })
  const { desktop } = useLayout()

  const [view, setView] = useState<StageView>(() => ({
    logical: initialStack(screenForPath(router.state.location.pathname) ?? 'today'),
    leaving: [],
    moving: [],
  }))
  const viewRef = useRef(view)
  const nodes = useRef(new Map<number, HTMLElement>())
  const stage = useRef<HTMLDivElement>(null)
  const shade = useRef<HTMLDivElement>(null)
  const busy = useRef(false)
  const job = useRef<Job | null>(null)
  const pending = useRef<string | null>(null)
  const swipe = useRef<Swipe | null>(null)

  const commit = (next: StageView) => {
    viewRef.current = next
    setView(next)
  }

  const scrollToTop = () => {
    const top = nodes.current.get(topOf(viewRef.current.logical).key)
    top?.scrollTo({ top: 0, behavior: prefersReducedMotion() ? 'auto' : 'smooth' })
  }

  const run = useEffectEvent(async ({ plan, shared }: Job) => {
    const from = plan.from === null ? undefined : nodes.current.get(plan.from.key)
    const to = plan.to === null ? undefined : nodes.current.get(plan.to.key)
    const stageEl = stage.current
    const shadeEl = shade.current
    try {
      if (from !== undefined && to !== undefined && stageEl !== null && shadeEl !== null) {
        const target =
          shared !== null && plan.motion !== 'pop' ? await whenPresent(() => to.querySelector<HTMLElement>('[data-shared-target]')) : null
        if (shared !== null && target !== null) {
          await sharedMorph(from, to, shared, target, stageEl.parentElement ?? stageEl)
        } else if (plan.motion === 'push') {
          await slide(from, to, shadeEl, stageEl.offsetWidth, 1)
        } else if (plan.motion === 'pop') {
          await slide(from, to, shadeEl, stageEl.offsetWidth, -1)
        } else {
          await fade(from, to)
        }
      }
    } finally {
      commit({ logical: viewRef.current.logical, leaving: [], moving: [] })
      busy.current = false
      const next = pending.current
      pending.current = null
      if (next !== null) sync(next)
    }
  })

  const sync = useEffectEvent((path: string) => {
    const id = screenForPath(path)
    if (id === null) return
    // A change that arrives mid-motion waits its turn; the stack and the address must end up agreeing.
    if (busy.current) {
      pending.current = path
      return
    }
    const intent = takeNavigationIntent()
    // Nobody announced it (the browser's back or forward, a pasted link): a screen already under
    // the top pops back to; anything else starts over.
    const plan = planGo(viewRef.current.logical, id, { mode: intent?.mode ?? 'tab', desktop })
    if (plan.motion === 'none' || plan.from === null || plan.to === null) {
      scrollToTop()
      return
    }
    busy.current = true
    job.current = { plan, shared: intent?.shared ?? null }
    commit({ logical: plan.state, leaving: plan.drop, moving: [plan.from.key, plan.to.key] })
  })

  useEffect(() => {
    sync(pathname)
  }, [pathname])

  // The frame around the stage follows the stack.
  useEffect(() => {
    const entries = view.logical.entries
    onStack({ root: (entries[0] as StackEntry).id, top: topOf(view.logical).id, depth: entries.length })
  }, [view.logical])

  useEffect(() => {
    window.addEventListener(SCROLL_TOP_EVENT, scrollToTop)
    return () => window.removeEventListener(SCROLL_TOP_EVENT, scrollToTop)
  }, [])

  // The plan is run once its screens are in the DOM and before they are painted.
  useLayoutEffect(() => {
    const next = job.current
    if (next === null) return
    job.current = null
    void run(next)
  }, [view])

  // Growing into a desktop window: only the screen on top stays.
  useEffect(() => {
    const v = viewRef.current
    if (desktop && v.logical.entries.length > 1) {
      commit({ logical: { ...v.logical, entries: [topOf(v.logical)] }, leaving: [], moving: [] })
    }
  }, [desktop])

  /* ---------- Swipe back from the left edge (phone) ---------- */
  const onPointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    const stageEl = stage.current
    const v = viewRef.current
    if (desktop || busy.current || v.logical.entries.length < 2 || stageEl === null) return
    if (e.pointerType === 'mouse' && e.button !== 0) return
    if (e.clientX - stageEl.getBoundingClientRect().left > EDGE) return
    const [top, under] = [v.logical.entries[v.logical.entries.length - 1], v.logical.entries[v.logical.entries.length - 2]]
    const topEl = top === undefined ? undefined : nodes.current.get(top.key)
    const underEl = under === undefined ? undefined : nodes.current.get(under.key)
    const shadeEl = shade.current
    if (top === undefined || under === undefined || topEl === undefined || underEl === undefined || shadeEl === null) return
    // Bring the screen below out of hiding for the length of the gesture.
    commit({ ...v, moving: [top.key, under.key] })
    underEl.style.zIndex = '1'
    shadeEl.style.zIndex = '2'
    topEl.style.zIndex = '3'
    topEl.style.boxShadow = '-24px 0 48px -18px rgba(0,0,0,.55)'
    swipe.current = { pointer: e.pointerId, x0: e.clientX, t0: performance.now(), top: topEl, under: underEl, width: stageEl.offsetWidth, dx: 0 }
    try {
      stageEl.setPointerCapture(e.pointerId)
    } catch {
      /* the pointer is already gone */
    }
  }

  const onPointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    const s = swipe.current
    if (s === null || e.pointerId !== s.pointer) return
    s.dx = Math.min(Math.max(e.clientX - s.x0, 0), s.width)
    const frame = swipeFrame(s.dx / s.width, s.width)
    s.top.style.transform = `translateX(${frame.top}px)`
    s.under.style.transform = `translateX(${frame.under}px)`
    if (shade.current !== null) shade.current.style.opacity = String(frame.shade)
  }

  const endSwipe = async (e: React.PointerEvent<HTMLDivElement>) => {
    const s = swipe.current
    const shadeEl = shade.current
    if (s === null || e.pointerId !== s.pointer || shadeEl === null) return
    swipe.current = null
    const progress = s.dx / s.width
    const velocity = s.dx / Math.max(1, performance.now() - s.t0)
    s.top.style.transform = ''
    s.under.style.transform = ''
    shadeEl.style.opacity = ''
    busy.current = true
    const v = viewRef.current
    if (swipeCommits(progress, velocity)) {
      const plan = planPop(v.logical)
      commit({ logical: plan.state, leaving: plan.drop, moving: v.moving })
      await slide(s.top, s.under, shadeEl, s.width, -1, progress)
      commit({ logical: plan.state, leaving: [], moving: [] })
      busy.current = false
      // The address follows the stack; the change finds the stack already there and does nothing.
      router.history.back()
    } else {
      const frame = swipeFrame(progress, s.width)
      await Promise.all([
        animate(s.top, [{ transform: `translateX(${frame.top}px)` }, { transform: 'none' }], { duration: 360 }).finished,
        animate(s.under, [{ transform: `translateX(${frame.under}px)` }, { transform: `translateX(${-s.width * 0.28}px)` }], { duration: 360 }).finished,
        animate(shadeEl, [{ opacity: frame.shade }, { opacity: 0.32 }], { duration: 360 }).finished,
      ])
      settle(s.top, s.under, shadeEl)
      for (const n of [s.top, s.under, shadeEl]) n.style.zIndex = ''
      s.top.style.boxShadow = ''
      commit({ ...viewRef.current, moving: [] })
      busy.current = false
    }
  }

  const top = topOf(view.logical)
  const mounted: StackEntry[] = [...view.logical.entries, ...view.leaving]
  return (
    <div
      ref={stage}
      className="stage"
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={endSwipe}
      onPointerCancel={endSwipe}
    >
      <div ref={shade} className="screen-shade" />
      {mounted.map((entry) => (
        <ScreenFrame
          key={entry.key}
          id={entry.id}
          hidden={entry.key !== top.key && !view.moving.includes(entry.key)}
          register={(node) => {
            if (node === null) nodes.current.delete(entry.key)
            else nodes.current.set(entry.key, node)
          }}
        >
          <ScreenProvider info={{ id: entry.id, back: desktop ? null : entry.back, firstVisit: entry.key === 0 }}>
            <ScreenBoundary id={entry.id}>
              <Suspense fallback={null}>
                <ScreenBody id={entry.id} />
              </Suspense>
            </ScreenBoundary>
          </ScreenProvider>
        </ScreenFrame>
      ))}
    </div>
  )
}

function ScreenBody({ id }: { id: ScreenId }) {
  const Screen = screenComponent(id)
  return <Screen />
}
