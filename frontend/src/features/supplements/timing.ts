/* The time of day a supplement is taken. The service takes free text and buckets it (morning, day,
   evening, night — anything else is "other"); the form offers the four and a text of one's own. */

export const TIMING_CHOICES = ['morning', 'day', 'evening', 'night'] as const
export const CUSTOM = 'custom'

/** A stored timing as the form holds it: one of the four, or "custom" with its own text. */
export function splitTiming(value: string | null | undefined): { choice: string; custom: string } {
  const text = (value ?? '').trim()
  if (text === '') return { choice: 'morning', custom: '' }
  const known = TIMING_CHOICES.find((c) => c === text.toLowerCase())
  return known === undefined ? { choice: CUSTOM, custom: text } : { choice: known, custom: '' }
}

/** What is saved: the chosen word, or the typed text; an empty custom text is no timing. */
export function joinTiming(choice: string, custom: string): string | null {
  if (choice !== CUSTOM) return choice
  const text = custom.trim()
  return text === '' ? null : text
}

/** Whether a row should say its timing: the group's name already says morning, day or evening. */
export const timingWorthShowing = (value: string | null | undefined): boolean => {
  const text = (value ?? '').trim().toLowerCase()
  return text !== '' && text !== 'morning' && text !== 'day' && text !== 'evening'
}
