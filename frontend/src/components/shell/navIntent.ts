/* How the next navigation was asked for. A tap on a section tab, a row that goes deeper and
   a bar tab all end in the same URL change; the Stage needs to know which of them it was to
   pick the motion. The caller says so just before it navigates, the Stage takes it once. A
   change nobody announced — the browser's back and forward buttons, a pasted link — has none. */

import type { NavMode } from './stack'

export interface NavIntent {
  mode: NavMode
  /** The element that flies to the next screen (the weight figure), when there is one. */
  shared?: HTMLElement | null
}

let pending: NavIntent | null = null

export function announceNavigation(intent: NavIntent): void {
  pending = intent
}

export function takeNavigationIntent(): NavIntent | null {
  const intent = pending
  pending = null
  return intent
}
