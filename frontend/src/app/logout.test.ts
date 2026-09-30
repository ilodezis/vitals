import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const removeClient = vi.fn(async () => {})
vi.mock('./persist', () => ({ persister: { removeClient }, CACHE_MAX_AGE_MS: 1000 }))

const { queryClient } = await import('./queryClient')
const { logOut } = await import('./logout')

describe('logOut', () => {
  const replace = vi.fn()
  let fetchMock: ReturnType<typeof vi.fn>

  beforeEach(() => {
    fetchMock = vi.fn(async () => new Response(null, { status: 303 }))
    vi.stubGlobal('fetch', fetchMock)
    vi.stubGlobal('location', { replace })
    queryClient.setQueryData(['session'], { user: 'me' })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    removeClient.mockClear()
    replace.mockClear()
  })

  it('ends the session on the server, forgets the cache and opens the login form', async () => {
    await logOut()
    expect(fetchMock).toHaveBeenCalledWith('/logout', expect.objectContaining({ method: 'POST' }))
    expect(queryClient.getQueryData(['session'])).toBeUndefined()
    expect(removeClient).toHaveBeenCalledOnce()
    expect(replace).toHaveBeenCalledWith('/login')
  })

  it('still forgets everything when the request cannot be sent', async () => {
    fetchMock.mockRejectedValueOnce(new TypeError('offline'))
    await logOut()
    expect(removeClient).toHaveBeenCalledOnce()
    expect(replace).toHaveBeenCalledWith('/login')
  })
})
