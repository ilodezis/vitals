/* The three ways one screen hands over to another, as Web Animations. Durations, easings,
   the 0.28 parallax and the 0.32 shade are the mockup's (docs/design/mockup/src/app.js);
   under reduced motion every one of them is a cut. */

import { animate, EASE_OUT, prefersReducedMotion, settle } from '@/lib/motion'

/** How far the screen underneath slides while the new one covers it, as a share of the width. */
export const PARALLAX = 0.28
/** How dark the screen underneath goes at the end of a push. */
export const SHADE = 0.32
export const SLIDE_MS = 540

const RAISED_EDGE = '-24px 0 48px -18px rgba(0,0,0,.55)'

/** A push (dir 1): `b` slides in from the right over `a`. A pop (dir −1): `a` leaves to the
 *  right and `b` comes back. `fromProgress` is how far a gesture already carried the top screen
 *  (0–1), so the rest of the motion finishes from there. */
export async function slide(
  a: HTMLElement,
  b: HTMLElement,
  shade: HTMLElement,
  width: number,
  dir: 1 | -1,
  fromProgress = 0,
): Promise<void> {
  const duration = SLIDE_MS * (1 - fromProgress)
  const top = dir > 0 ? b : a
  const under = dir > 0 ? a : b
  b.style.display = ''
  b.hidden = false
  under.style.zIndex = '1'
  shade.style.zIndex = '2'
  top.style.zIndex = '3'
  top.style.boxShadow = RAISED_EDGE

  const p0 = dir > 0 ? 1 : fromProgress
  const p1 = dir > 0 ? 0 : 1
  const u0 = dir > 0 ? 0 : -PARALLAX * (1 - fromProgress)
  const u1 = dir > 0 ? -PARALLAX : 0
  const s0 = dir > 0 ? 0 : SHADE * (1 - fromProgress)
  const s1 = dir > 0 ? SHADE : 0
  await Promise.all([
    animate(top, [{ transform: `translateX(${p0 * width}px)` }, { transform: `translateX(${p1 * width}px)` }], { duration }).finished,
    animate(under, [{ transform: `translateX(${u0 * width}px)` }, { transform: `translateX(${u1 * width}px)` }], { duration }).finished,
    animate(shade, [{ opacity: s0 }, { opacity: s1 }], { duration }).finished,
  ])
  a.hidden = true
  a.style.display = 'none'
  settle(top, under, shade)
  for (const n of [top, under, shade]) n.style.zIndex = ''
  top.style.boxShadow = ''
}

/** A tab, a section tab, any change on the desktop: the old screen leaves fast and linear, the new
 *  one fades in where it stands. It does not move: with its content drawn from the first frame, a
 *  rise from below reads as the page jumping down and coming back. */
export async function fade(a: HTMLElement | null, b: HTMLElement): Promise<void> {
  b.style.display = ''
  b.hidden = false
  b.style.zIndex = '2'
  if (a !== null) a.style.zIndex = '1'
  const jobs = [
    animate(b, [{ opacity: 0 }, { opacity: 1 }], { duration: 380, delay: 40, easing: EASE_OUT }).finished,
  ]
  if (a !== null) jobs.push(animate(a, [{ opacity: 1 }, { opacity: 0 }], { duration: 140, easing: 'linear' }).finished)
  await Promise.all(jobs)
  if (a !== null) {
    a.hidden = true
    a.style.display = 'none'
  }
  settle(a, b)
  b.style.zIndex = ''
  if (a !== null) a.style.zIndex = ''
}

/** The element once it exists. A screen that was only just loaded may still be drawing itself when
 *  the motion starts; this waits for it a moment instead of giving the motion up. Timers, not
 *  frames: a hidden page draws none, and the navigation must not hang on it. */
export async function whenPresent<T>(find: () => T | null, timeoutMs = 500, stepMs = 16): Promise<T | null> {
  for (let waited = 0; ; waited += stepMs) {
    const found = find()
    if (found !== null || waited >= timeoutMs) return found
    await new Promise<void>((resolve) => setTimeout(resolve, stepMs))
  }
}

/** The weight figure leaves Today and lands as the Weight page's hero: a clone flies from one
 *  to the other while the new screen fades up beneath it. */
export async function sharedMorph(
  a: HTMLElement,
  b: HTMLElement,
  source: HTMLElement,
  target: HTMLElement,
  host: HTMLElement,
): Promise<void> {
  if (prefersReducedMotion()) return fade(a, b)
  const root = host.getBoundingClientRect()
  const r0 = source.getBoundingClientRect()
  const r1 = target.getBoundingClientRect()
  const fs0 = Number.parseFloat(getComputedStyle(source).fontSize)
  const fs1 = Number.parseFloat(getComputedStyle(target).fontSize)

  const flyer = source.cloneNode(true) as HTMLElement
  flyer.classList.add('flyer')
  Object.assign(flyer.style, {
    left: `${r0.left - root.left}px`,
    top: `${r0.top - root.top}px`,
    fontSize: `${fs0}px`,
    width: 'auto',
  })
  host.appendChild(flyer)
  source.style.visibility = 'hidden'
  target.style.visibility = 'hidden'
  b.style.display = ''
  b.hidden = false
  b.style.zIndex = '2'
  a.style.zIndex = '1'

  const dx = r1.left - r0.left
  const dy = r1.top - r0.top
  const scale = fs1 / fs0
  await Promise.all([
    animate(flyer, [{ transform: 'none' }, { transform: `translate(${dx}px, ${dy}px) scale(${scale})` }], { duration: 620 }).finished,
    animate(b, [{ opacity: 0, transform: 'scale(.985)' }, { opacity: 1, transform: 'none' }], { duration: 460, delay: 90, easing: EASE_OUT }).finished,
    animate(a, [{ opacity: 1 }, { opacity: 0 }], { duration: 220, easing: 'linear' }).finished,
  ])
  target.style.visibility = ''
  source.style.visibility = ''
  flyer.remove()
  a.hidden = true
  a.style.display = 'none'
  settle(a, b)
  a.style.zIndex = ''
  b.style.zIndex = ''
}

/** The edge swipe decides by distance or by speed: past 35% of the width, or fast (0.5 px/ms)
 *  and past 8%. */
export function swipeCommits(progress: number, velocity: number): boolean {
  return progress > 0.35 || (velocity > 0.5 && progress > 0.08)
}

/** The sheet closes when dragged past 28% of its height, or faster than 0.6 px/ms. */
export function sheetCloses(dragged: number, height: number, velocity: number): boolean {
  return dragged > height * 0.28 || velocity > 0.6
}

/** The gesture's screen positions for a given progress (0–1): the top screen follows the finger,
 *  the one underneath drifts back by the parallax, the shade lifts. */
export function swipeFrame(progress: number, width: number): { top: number; under: number; shade: number } {
  return { top: progress * width, under: -PARALLAX * width * (1 - progress), shade: SHADE * (1 - progress) }
}
