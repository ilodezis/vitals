/** The two 0–5 scores of a skin observation, as typed. A score left empty is sent as "not rated"
 *  (`null`), never as a number the person did not enter; with neither score there is nothing to
 *  record, and a score that is not a whole number from 0 to 5 keeps the form unsaved. */

const UNREADABLE = Symbol('unreadable')

function readScore(raw: string): number | null | typeof UNREADABLE {
  const text = raw.trim()
  if (text === '') return null
  if (!/^\d+$/.test(text)) return UNREADABLE
  const value = Number(text)
  return value <= 5 ? value : UNREADABLE
}

export function buildObservationScores(fields: {
  inflammation: string
  pih: string
}): { inflammation: number | null; pih: number | null } | null {
  const inflammation = readScore(fields.inflammation)
  const pih = readScore(fields.pih)
  if (inflammation === UNREADABLE || pih === UNREADABLE) return null
  if (inflammation === null && pih === null) return null
  return { inflammation, pih }
}
