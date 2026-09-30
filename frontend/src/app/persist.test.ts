import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { PersistedClient } from '@tanstack/react-query-persist-client'

vi.mock('idb-keyval', () => ({ get: vi.fn(), set: vi.fn(), del: vi.fn() }))
vi.stubGlobal('__API_BUSTER__', 'test')

const { createPersister } = await import('./persist')

const snapshot = (n: number) => ({ timestamp: n, buster: 'b', clientState: { queries: [], mutations: [] } }) as PersistedClient

describe('createPersister', () => {
  const storage = { set: vi.fn(async () => {}), get: vi.fn(async () => undefined), del: vi.fn(async () => {}) }

  beforeEach(() => vi.useFakeTimers())
  afterEach(() => {
    vi.useRealTimers()
    storage.set.mockClear()
    storage.del.mockClear()
  })

  it('writes a burst of changes once, with the newest state', async () => {
    const persister = createPersister(storage, 1000)
    for (let i = 1; i <= 5; i++) await persister.persistClient(snapshot(i))
    expect(storage.set).not.toHaveBeenCalled()

    await vi.advanceTimersByTimeAsync(1000)
    expect(storage.set).toHaveBeenCalledOnce()
    expect(storage.set).toHaveBeenCalledWith('vitals-query-cache', snapshot(5))
  })

  it('writes again for a change that comes after the last write', async () => {
    const persister = createPersister(storage, 1000)
    await persister.persistClient(snapshot(1))
    await vi.advanceTimersByTimeAsync(1000)
    await persister.persistClient(snapshot(2))
    await vi.advanceTimersByTimeAsync(1000)
    expect(storage.set).toHaveBeenCalledTimes(2)
    expect(storage.set).toHaveBeenLastCalledWith('vitals-query-cache', snapshot(2))
  })

  it('drops a waiting write when the cache is removed', async () => {
    const persister = createPersister(storage, 1000)
    await persister.persistClient(snapshot(1))
    await persister.removeClient()
    await vi.advanceTimersByTimeAsync(1000)
    expect(storage.del).toHaveBeenCalledOnce()
    expect(storage.set).not.toHaveBeenCalled()
  })

  it('treats a storage that refuses as no storage', async () => {
    const refusing = { ...storage, set: vi.fn(async () => Promise.reject(new Error('quota'))) }
    const persister = createPersister(refusing, 10)
    await persister.persistClient(snapshot(1))
    await expect(vi.advanceTimersByTimeAsync(10)).resolves.not.toThrow()
  })
})
