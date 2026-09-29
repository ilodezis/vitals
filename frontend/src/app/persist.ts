import { del, get, set } from 'idb-keyval'
import type { PersistedClient, Persister } from '@tanstack/react-query-persist-client'

/** How long the device keeps what it was told. Also the cache's `gcTime`, which may not be shorter. */
export const CACHE_MAX_AGE_MS = 24 * 60 * 60 * 1000

/** The cache is dropped whenever the API's contract changes: what an older build stored may not
 *  fit the screens of this one. `__API_BUSTER__` is a hash of the committed OpenAPI schema. */
export const CACHE_BUSTER: string = __API_BUSTER__

const KEY = 'vitals-query-cache'

/** The query cache in IndexedDB. Storage that is missing or refuses (a private window, a full
 *  disk) is not an error: the app then simply opens from the network, as it did before. */
export const persister: Persister = {
  persistClient: async (client: PersistedClient) => {
    try {
      await set(KEY, client)
    } catch {
      /* nothing to keep it in */
    }
  },
  restoreClient: async () => {
    try {
      return await get<PersistedClient>(KEY)
    } catch {
      return undefined
    }
  },
  removeClient: async () => {
    try {
      await del(KEY)
    } catch {
      /* already gone */
    }
  },
}
