/* "Add an event" asked for from another screen (Today's quick chip): the timeline opens its add
   form when it next draws, or at once if it is already on screen. */

let pending = false
const listeners = new Set<() => void>()

export function requestNewEvent(): void {
  pending = true
  for (const listener of listeners) listener()
}

/** Whether a request is waiting, without taking it: safe to ask while drawing. */
export const hasNewEventRequest = (): boolean => pending

/** Whether a request is waiting; reading it clears it, so the form opens once. */
export function takeNewEventRequest(): boolean {
  const was = pending
  pending = false
  return was
}

export function onNewEventRequest(listener: () => void): () => void {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}
