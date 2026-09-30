import { describe, expect, it, vi } from 'vitest'
import workerSource from '../sw.ts?raw'
import { reloadOnNewWorker } from './swUpdate'

function container(controller: object | null) {
  const listeners: (() => void)[] = []
  return {
    controller,
    addEventListener: (_type: 'controllerchange', listener: () => void) => void listeners.push(listener),
    takeOver: () => listeners.forEach((listener) => listener()),
  }
}

describe('picking up a new build', () => {
  it('reloads the page once when a new worker replaces the one that served it', () => {
    const sw = container({})
    const reload = vi.fn()
    reloadOnNewWorker(sw, reload)

    sw.takeOver()
    sw.takeOver()

    expect(reload).toHaveBeenCalledTimes(1)
  })

  it('leaves the very first visit alone: there the worker only starts caching', () => {
    const sw = container(null)
    const reload = vi.fn()
    reloadOnNewWorker(sw, reload)

    sw.takeOver()

    expect(reload).not.toHaveBeenCalled()
  })

  it('the worker takes over at once instead of waiting for every tab to close', () => {
    expect(workerSource).toMatch(/self\.skipWaiting\(\)/)
    expect(workerSource).toMatch(/self\.clients\.claim\(\)/)
  })
})
