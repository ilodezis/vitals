import { del, get, set } from 'idb-keyval'
import type { PersistedClient, Persister } from '@tanstack/react-query-persist-client'

/** How long the device keeps what it was told. Also the cache's `gcTime`, which may not be shorter. */
export const CACHE_MAX_AGE_MS = 24 * 60 * 60 * 1000

/** The cache is dropped whenever the API's contract changes: what an older build stored may not
 *  fit the screens of this one. `__API_BUSTER__` is a hash of the committed OpenAPI schema. */
export const CACHE_BUSTER: string = __API_BUSTER__

const KEY = 'vitals-query-cache'

/** How often the cache is written out at most. The provider asks on every change a query goes
 *  through (a fetch starting, its answer landing), and every write copies the whole cache into
 *  storage on the main thread — several times per screen change, in the middle of its motion. */
export const PERSIST_THROTTLE_MS = 1000

interface Storage {
  set: (key: string, value: PersistedClient) => Promise<void>
  get: (key: string) => Promise<PersistedClient | undefined>
  del: (key: string) => Promise<void>
}

/** The query cache in IndexedDB. Storage that is missing or refuses (a private window, a full
 *  disk) is not an error: the app then simply opens from the network, as it did before.
 *
 *  Writes are coalesced: the newest state is written at most once per `throttleMs`, and at once
 *  when the page is hidden, so an app swiped away keeps what it had just been told. */
export function createPersister(storage: Storage = { set, get, del }, throttleMs = PERSIST_THROTTLE_MS): Persister {
  let pending: PersistedClient | null = null
  let timer: ReturnType<typeof setTimeout> | null = null

  const write = async () => {
    if (timer !== null) clearTimeout(timer)
    timer = null
    const client = pending
    pending = null
    if (client === null) return
    try {
      await storage.set(KEY, client)
    } catch {
      /* nothing to keep it in */
    }
  }

  if (typeof document !== 'undefined') {
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'hidden') void write()
    })
  }

  return {
    persistClient: (client: PersistedClient) => {
      pending = client
      if (timer === null) timer = setTimeout(() => void write(), throttleMs)
    },
    restoreClient: async () => {
      try {
        return await storage.get(KEY)
      } catch {
        return undefined
      }
    },
    removeClient: async () => {
      // A write still waiting would bring back what is being dropped.
      if (timer !== null) clearTimeout(timer)
      timer = null
      pending = null
      try {
        await storage.del(KEY)
      } catch {
        /* already gone */
      }
    },
  }
}

export const persister: Persister = createPersister()
