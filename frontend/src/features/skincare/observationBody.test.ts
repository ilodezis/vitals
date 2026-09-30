import { describe, expect, it } from 'vitest'
import { buildObservationScores } from './observationBody'

describe('buildObservationScores', () => {
  it('reads both scores as typed, zero included', () => {
    expect(buildObservationScores({ inflammation: '3', pih: '0' })).toEqual({ inflammation: 3, pih: 0 })
  })

  it('sends a score left empty as not rated, not as a number', () => {
    expect(buildObservationScores({ inflammation: '2', pih: '' })).toEqual({ inflammation: 2, pih: null })
    expect(buildObservationScores({ inflammation: ' ', pih: '4' })).toEqual({ inflammation: null, pih: 4 })
  })

  it('has no body when neither score was entered', () => {
    expect(buildObservationScores({ inflammation: '', pih: '' })).toBeNull()
  })

  it('has no body for a score off the 0–5 scale or not a whole number', () => {
    for (const bad of ['6', '-1', '2.5', 'abc']) {
      expect(buildObservationScores({ inflammation: bad, pih: '1' })).toBeNull()
      expect(buildObservationScores({ inflammation: '1', pih: bad })).toBeNull()
    }
  })
})
