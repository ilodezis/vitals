import { afterEach, describe, expect, it, vi } from 'vitest'
import { ConflictError, InvalidError, createApiClient } from './client'

const SESSION = {
  username: 'tester',
  lang: 'ru',
  enabled_modules: { weight: true },
  nav: { items: [], bottom_slots: [], more_rubrics: [], more_routes: [] },
  rail: [],
}

const VIOLATION = {
  rule_id: 7,
  rule_type: 'pair',
  severity: 'block',
  message: 'Not together.',
  domain_a: 'glp1',
  domain_b: 'supplements',
  params: {},
  category: null,
  source: null,
  evidence: null,
}

function reply(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function clientAnswering(respond: (request: Request) => Response) {
  const fetchMock = vi.fn(async (request: Request) => respond(request))
  const api = createApiClient({
    baseUrl: 'http://localhost',
    fetch: fetchMock as unknown as typeof fetch,
  })
  return { api, fetchMock }
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('api client', () => {
  it('sends the session cookie to its own origin', async () => {
    const { api, fetchMock } = clientAnswering(() => reply(200, SESSION))

    await api.GET('/api/v1/session')

    const request = fetchMock.mock.calls[0]?.[0]
    expect(request?.credentials).toBe('same-origin')
    expect(new URL(request?.url ?? '').pathname).toBe('/api/v1/session')
  })

  it('returns the typed body on success', async () => {
    const { api } = clientAnswering(() => reply(200, SESSION))

    const { data, error } = await api.GET('/api/v1/session')

    expect(error).toBeUndefined()
    expect(data?.username).toBe('tester')
    expect(data?.lang).toBe('ru')
  })

  it('sends a signed-out visitor to the login form and back again', async () => {
    const assign = vi.fn()
    vi.stubGlobal('location', { assign, pathname: '/app/weight', search: '?range=3m' })
    const { api } = clientAnswering(() => reply(401, { error: 'unauthenticated' }))

    await api.GET('/api/v1/session')

    expect(assign).toHaveBeenCalledExactlyOnceWith('/login?next=%2Fapp%2Fweight%3Frange%3D3m')
  })

  it('turns a blocked write into a ConflictError carrying the violations', async () => {
    const { api } = clientAnswering(() =>
      reply(409, { error: 'conflict', violations: [VIOLATION] }),
    )

    const failure = await api.GET('/api/v1/session').catch((e: unknown) => e)

    expect(failure).toBeInstanceOf(ConflictError)
    const conflict = failure as ConflictError
    expect(conflict.violations).toEqual([VIOLATION])
    expect(conflict.message).toBe('Not together.')
  })

  it('still raises a ConflictError when the 409 body is not the expected one', async () => {
    const { api } = clientAnswering(() => new Response('<html>oops</html>', { status: 409 }))

    const failure = await api.GET('/api/v1/session').catch((e: unknown) => e)

    expect(failure).toBeInstanceOf(ConflictError)
    expect((failure as ConflictError).violations).toEqual([])
  })

  it('turns a refused value into an InvalidError with the service’s own message', async () => {
    const { api } = clientAnswering(() =>
      reply(400, { error: 'invalid', message: 'weight_kg must be between 20 and 400' }),
    )

    const failure = await api.GET('/api/v1/session').catch((e: unknown) => e)

    expect(failure).toBeInstanceOf(InvalidError)
    expect((failure as InvalidError).message).toBe('weight_kg must be between 20 and 400')
  })

  it('still raises an InvalidError when the 400 body is not the expected one', async () => {
    const { api } = clientAnswering(() => new Response('<html>oops</html>', { status: 400 }))

    const failure = await api.GET('/api/v1/session').catch((e: unknown) => e)

    expect(failure).toBeInstanceOf(InvalidError)
    expect((failure as InvalidError).message).toBe('Invalid')
  })

  it('hands every other failure back as data, unredirected', async () => {
    const assign = vi.fn()
    vi.stubGlobal('location', { assign, pathname: '/app/glp1', search: '' })
    const { api } = clientAnswering(() => reply(404, { error: 'module_disabled' }))

    const { data, error, response } = await api.GET('/api/v1/session')

    expect(data).toBeUndefined()
    expect(error).toEqual({ error: 'module_disabled' })
    expect(response.status).toBe(404)
    expect(assign).not.toHaveBeenCalled()
  })
})
