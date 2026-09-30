import { describe, expect, it } from 'vitest'
import { pressConfirm } from './ConfirmButton'

describe('pressConfirm', () => {
  it('asks on the first press and acts on the second', () => {
    expect(pressConfirm(false)).toEqual({ armed: true, fire: false })
    expect(pressConfirm(true)).toEqual({ armed: false, fire: true })
  })
})
