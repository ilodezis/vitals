import { describe, expect, it, vi } from 'vitest'
import { hasNewEventRequest, onNewEventRequest, requestNewEvent, takeNewEventRequest } from './newEventIntent'

describe('new event request', () => {
  it('is taken once', () => {
    requestNewEvent()
    expect(hasNewEventRequest()).toBe(true)
    expect(hasNewEventRequest()).toBe(true)
    expect(takeNewEventRequest()).toBe(true)
    expect(hasNewEventRequest()).toBe(false)
    expect(takeNewEventRequest()).toBe(false)
  })

  it('tells a timeline already on screen', () => {
    const listener = vi.fn()
    const off = onNewEventRequest(listener)
    requestNewEvent()
    expect(listener).toHaveBeenCalledOnce()
    off()
    requestNewEvent()
    expect(listener).toHaveBeenCalledOnce()
    takeNewEventRequest()
  })
})
