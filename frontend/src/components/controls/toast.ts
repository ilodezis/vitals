/* Toasts: the small confirmation that a record was saved, with "Undo" when it can be
   taken back. A module-level store, so any code — a sheet, a mutation's callback — can
   raise one without threading props; <ToastHost> draws them. */

import { useSyncExternalStore } from 'react'
import type { IconName } from '@/components/icons/Icon'

export interface ToastItem {
  id: number
  text: string
  icon: IconName
  undo?: () => void
  /** Fading out: still drawn, no longer counted. */
  leaving: boolean
}

let items: readonly ToastItem[] = []
let nextId = 1
const listeners = new Set<() => void>()

const emit = () => listeners.forEach((l) => l())
const subscribe = (l: () => void) => {
  listeners.add(l)
  return () => listeners.delete(l)
}

export const useToasts = (): readonly ToastItem[] => useSyncExternalStore(subscribe, () => items)

const LEAVE_MS = 220

export function dismissToast(id: number): void {
  if (!items.some((t) => t.id === id && !t.leaving)) return
  items = items.map((t) => (t.id === id ? { ...t, leaving: true } : t))
  emit()
  setTimeout(() => {
    items = items.filter((t) => t.id !== id)
    emit()
  }, LEAVE_MS)
}

/** Show a toast. One with an undo stays a little longer, so there is time to use it. */
export function toast(text: string, options: { undo?: () => void; icon?: IconName } = {}): number {
  const id = nextId++
  items = [...items, { id, text, icon: options.icon ?? 'check', undo: options.undo, leaving: false }]
  emit()
  setTimeout(() => dismissToast(id), options.undo === undefined ? 2600 : 4200)
  return id
}
