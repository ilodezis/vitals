import { describe, expect, it, vi } from 'vitest'
import { ConflictError, createApiClient, failText, InvalidError, ok, RequestError, type Violation } from './client'

const response = (status: number) => ({ status }) as Response

const VIOLATION: Violation = {
  rule_id: 1,
  rule_type: 'conflict',
  severity: 'block',
  message: 'Retinoid and peel on the same day.',
  domain_a: 'skincare',
  domain_b: 'skincare',
  params: {},
  category: 'dermatology',
  source: null,
  evidence: null,
}

describe('ok', () => {
  it('hands back the data of an answer that went through', async () => {
    await expect(ok(Promise.resolve({ data: { id: 7 }, response: response(200) }))).resolves.toEqual({ id: 7 })
  })

  it('accepts a 204 with nothing in it', async () => {
    await expect(ok(Promise.resolve({ data: undefined, response: response(204) }))).resolves.toBeUndefined()
  })

  it('throws on an error body: openapi-fetch does not, and a "Saved" toast must not follow a 404', async () => {
    const answer = Promise.resolve({ data: undefined, error: { error: 'not_found' }, response: response(404) })
    await expect(ok(answer)).rejects.toMatchObject({ name: 'RequestError', status: 404 })
  })

  it('throws on a server error even when it came with no body', async () => {
    await expect(ok(Promise.resolve({ data: undefined, response: response(500) }))).rejects.toBeInstanceOf(RequestError)
  })

  it('lets a network failure through as it is', async () => {
    await expect(ok(Promise.reject(new TypeError('Failed to fetch')))).rejects.toThrow('Failed to fetch')
  })

  it('turns what the real client hands back for a 500 into a throw', async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ error: 'boom' }), { status: 500, headers: { 'Content-Type': 'application/json' } }))
    const api = createApiClient({ baseUrl: 'http://localhost', fetch: fetchMock as unknown as typeof fetch })

    const { data, error } = await api.GET('/api/v1/session')
    expect(data).toBeUndefined()
    expect(error).toBeDefined() // the client itself says nothing: this is what `ok` is for

    await expect(ok(api.GET('/api/v1/session'))).rejects.toMatchObject({ name: 'RequestError', status: 500 })
  })
})

describe('failText', () => {
  it("gives a service's own words for a refused value", () => {
    expect(failText(new InvalidError('Weight must be above 30 kg.'), 'Could not save.')).toBe('Weight must be above 30 kg.')
  })

  it("gives the rules' words for a blocked write", () => {
    expect(failText(new ConflictError([VIOLATION]), 'Could not save.')).toBe('Retinoid and peel on the same day.')
  })

  it('gives the screen its own line when the refusal came without a reason', () => {
    expect(failText(new InvalidError('Invalid'), 'Could not save.')).toBe('Could not save.')
    expect(failText(new InvalidError(''), 'Could not save.')).toBe('Could not save.')
  })

  it('never prints the text of an exception', () => {
    expect(failText(new RequestError(500), 'Could not save.')).toBe('Could not save.')
    expect(failText(new TypeError('Failed to fetch'), 'Could not save.')).toBe('Could not save.')
    expect(failText('boom', 'Could not save.')).toBe('Could not save.')
  })
})
