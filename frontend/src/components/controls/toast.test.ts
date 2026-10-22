import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { currentToasts, dismissToast, toast, updateToast } from './toast'

const shown = () => currentToasts().filter((t) => !t.leaving)

describe('toast', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => {
    vi.runAllTimers()
    vi.useRealTimers()
  })

  it('goes away by itself', () => {
    toast('Saved')
    vi.advanceTimersByTime(3000)
    expect(shown().map((t) => t.text)).not.toContain('Saved')
  })

  it('keeps a persistent status up until it is dismissed', () => {
    const id = toast('Uploading', { persist: true, progress: 0 })
    vi.advanceTimersByTime(60_000)
    expect(shown().find((t) => t.id === id)?.text).toBe('Uploading')
    dismissToast(id)
    expect(shown().find((t) => t.id === id)).toBeUndefined()
  })

  it('moves a shown status on in place', () => {
    const id = toast('Uploading 0%', { persist: true, progress: 0 })
    updateToast(id, { text: 'Uploading 40%', progress: 0.4 })
    expect(shown().find((t) => t.id === id)).toMatchObject({ text: 'Uploading 40%', progress: 0.4 })
    dismissToast(id)
  })

  it('does not bring back a toast already dismissed', () => {
    const id = toast('Uploading', { persist: true })
    dismissToast(id)
    updateToast(id, { text: 'late' })
    expect(shown().find((t) => t.id === id)).toBeUndefined()
  })
})
