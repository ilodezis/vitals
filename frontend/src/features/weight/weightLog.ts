/* Logging a weight, on fixtures. The real API replaces this later: `POST /api/v1/weight/logs`
   with an optimistic update, a 409 that carries the conflict engine's violations, and a DELETE for
   the toast's "Undo". Everything the screens call — `logWeight`, `useLoggedWeight` — keeps the
   shape it will have then, so only this file changes. */

import { useSyncExternalStore } from 'react'
import { ConflictError, type Violation } from '@/api/client'
import { wait } from '@/lib/motion'
import { latestWeight } from '@/fixtures/series'

/** A reading this far from the last one, within hours, is held for confirmation. */
export const CONFLICT_STEP_KG = 1.5

export interface LoggedWeight {
  kg: number
  /** Readings saved this session, newest last: the day's feed shows them. */
  added: { id: number; kg: number; at: string }[]
}

let state: LoggedWeight = { kg: latestWeight, added: [] }
let nextId = 1
const listeners = new Set<() => void>()
const emit = () => listeners.forEach((l) => l())
const subscribe = (l: () => void) => {
  listeners.add(l)
  return () => listeners.delete(l)
}

export const useLoggedWeight = (): LoggedWeight => useSyncExternalStore(subscribe, () => state)
export const currentWeight = (): number => state.kg

export interface LogWeightOptions {
  override: boolean
  /** The clock time to stamp the reading with. */
  at: string
  /** Say why a jump is held back, in the user's language. */
  conflictMessage: (deltaKg: number) => string
}

function violationFor(message: string): Violation {
  return {
    rule_id: null,
    rule_type: 'jump',
    severity: 'block',
    message,
    domain_a: 'weight',
    domain_b: 'weight',
    params: {},
    category: null,
    source: null,
    evidence: null,
  }
}

/** Save a reading. Throws `ConflictError` when it is a jump the conflict engine would block and
 *  `override` is off; otherwise returns an `undo` that takes it back. */
export async function logWeight(kg: number, options: LogWeightOptions): Promise<{ undo: () => void }> {
  await wait(520)
  const delta = kg - state.kg
  if (!options.override && Math.abs(delta) >= CONFLICT_STEP_KG) {
    throw new ConflictError([violationFor(options.conflictMessage(delta))])
  }
  const previous = state
  const id = nextId++
  state = { kg, added: [...state.added, { id, kg, at: options.at }] }
  emit()
  return {
    undo: () => {
      state = { kg: previous.kg, added: state.added.filter((a) => a.id !== id) }
      emit()
    },
  }
}
