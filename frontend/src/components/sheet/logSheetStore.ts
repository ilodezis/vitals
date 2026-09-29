/* The log sheet's state: open or shut, which tab. A store outside React so the "+" in the bar,
   the "Log" in the rail, a quick chip on Today and the N key all open the same sheet. */

import { useSyncExternalStore } from 'react'

export type LogTab = 'weight' | 'meal' | 'dose' | 'measure'

export interface LogSheetState {
  open: boolean
  tab: LogTab
  /** Counts openings: every opening starts the forms fresh. */
  opening: number
  /** The tab was changed since the sheet opened: the new pane slides in; the first one does not. */
  switched: boolean
}

let state: LogSheetState = { open: false, tab: 'weight', opening: 0, switched: false }
const listeners = new Set<() => void>()
const set = (next: LogSheetState) => {
  state = next
  listeners.forEach((l) => l())
}
const subscribe = (l: () => void) => {
  listeners.add(l)
  return () => listeners.delete(l)
}

export const useLogSheet = (): LogSheetState => useSyncExternalStore(subscribe, () => state)

export const openLogSheet = (tab: LogTab = 'weight'): void =>
  set({ open: true, tab, opening: state.open ? state.opening : state.opening + 1, switched: false })
export const closeLogSheet = (): void => {
  if (state.open) set({ ...state, open: false })
}
/** The "+" is a toggle: pressed again it closes what it opened. */
export const toggleLogSheet = (tab: LogTab = 'weight'): void => (state.open ? closeLogSheet() : openLogSheet(tab))
export const setLogTab = (tab: LogTab): void => set({ ...state, tab, switched: true })
