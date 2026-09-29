/* The motion vocabulary in code: the easings the tokens name, the durations the mockup
   fixed, and a Web Animations wrapper that turns every motion into a cut when the user
   asked for reduced motion. Timings are the mockup's (docs/design/mockup/src/app.js). */

import { useSyncExternalStore } from 'react'

export const EASE_SHEET = 'cubic-bezier(.32,.72,0,1)'
export const EASE_OUT = 'cubic-bezier(.16,1,.3,1)'

const QUERY = '(prefers-reduced-motion: reduce)'

export const prefersReducedMotion = (): boolean =>
  typeof matchMedia === 'function' && matchMedia(QUERY).matches

function subscribe(notify: () => void): () => void {
  const mq = matchMedia(QUERY)
  mq.addEventListener('change', notify)
  return () => mq.removeEventListener('change', notify)
}

export const useReducedMotion = (): boolean =>
  useSyncExternalStore(subscribe, prefersReducedMotion, () => false)

/** `node.animate()` that holds its end state, defaults to the sheet easing, and lasts one
 *  millisecond under reduced motion. Cancel the returned animation to release the fill. */
export function animate(
  node: Element,
  keyframes: Keyframe[],
  options: { duration: number; delay?: number; easing?: string },
): Animation {
  return node.animate(keyframes, {
    fill: 'both',
    easing: EASE_SHEET,
    ...options,
    duration: prefersReducedMotion() ? 1 : options.duration,
    delay: prefersReducedMotion() ? 0 : (options.delay ?? 0),
  })
}

/** Release the fill of every animation on a node once its motion is over. */
export function settle(...nodes: Array<Element | null | undefined>): void {
  for (const node of nodes) node?.getAnimations().forEach((a) => a.cancel())
}

export const wait = (ms: number): Promise<void> =>
  new Promise((resolve) => setTimeout(resolve, prefersReducedMotion() ? 0 : ms))
