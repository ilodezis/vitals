import { QueryClient } from '@tanstack/react-query'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ConflictError, InvalidError } from '@/api/client'
import { sampleTodayView } from '@/fixtures/todayView'
import { todayQuery } from '@/features/today/useTodayView'
import { saveWeight } from './weightLog'

const { POST, DELETE } = vi.hoisted(() => ({ POST: vi.fn(), DELETE: vi.fn() }))
vi.mock('@/api/client', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/api/client')>()),
  api: { POST, DELETE },
}))

const weightOf = (client: QueryClient) =>
  client.getQueryData(todayQuery.queryKey)?.figures.find((f) => f.key === 'weight')?.value

function clientWithToday() {
  const client = new QueryClient()
  client.setQueryData(todayQuery.queryKey, sampleTodayView())
  client.setQueryData(['session'], { username: 'tester' })
  return client
}

beforeEach(() => {
  POST.mockReset()
  DELETE.mockReset()
})

describe('saveWeight', () => {
  it('shows the new weight before the server has answered', async () => {
    const client = clientWithToday()
    let answer: (v: unknown) => void = () => undefined
    POST.mockReturnValue(new Promise((resolve) => (answer = resolve)))

    const saving = saveWeight(client, 85.5, { override: false })
    await vi.waitFor(() => expect(weightOf(client)).toBe(85.5))
    answer({ data: { id: 7, created: true } })
    await saving
  })

  it('writes to the day the server calls today', async () => {
    const client = clientWithToday()
    POST.mockResolvedValue({ data: { id: 7, created: true } })

    await saveWeight(client, 85.5, { override: true })

    expect(POST).toHaveBeenCalledExactlyOnceWith('/api/v1/weight/logs', {
      body: { date: '2026-09-29', weight_kg: 85.5, override: true },
    })
  })

  it('asks the server again once it is saved, for the day and for the rail', async () => {
    const client = clientWithToday()
    POST.mockResolvedValue({ data: { id: 7, created: true } })

    await saveWeight(client, 85.5, { override: false })

    expect(client.getQueryState(todayQuery.queryKey)?.isInvalidated).toBe(true)
    expect(client.getQueryState(['session'])?.isInvalidated).toBe(true)
  })

  it('takes the number back when the server blocks it, and says why', async () => {
    const client = clientWithToday()
    const conflict = new ConflictError([
      { rule_id: 1, rule_type: 'hard_block', severity: 'block', message: 'Too far in a day.', domain_a: 'weight', domain_b: 'weight', params: {}, category: null, source: null, evidence: null },
    ])
    POST.mockRejectedValue(conflict)

    await expect(saveWeight(client, 90, { override: false })).rejects.toBe(conflict)

    expect(weightOf(client)).toBe(86.1)
    expect(client.getQueryData(todayQuery.queryKey)?.feed.some((r) => r.kind === 'weight')).toBe(false)
    expect(client.getQueryData(todayQuery.queryKey)?.goal?.current_kg).toBe(86.1)
  })

  it('takes the number back when the service refuses it', async () => {
    const client = clientWithToday()
    const invalid = new InvalidError('weight_kg must be between 20 and 400')
    POST.mockRejectedValue(invalid)

    await expect(saveWeight(client, 900, { override: false })).rejects.toBe(invalid)

    expect(weightOf(client)).toBe(86.1)
  })

  it('takes the number back when the network fails', async () => {
    const client = clientWithToday()
    POST.mockRejectedValue(new TypeError('Failed to fetch'))

    await expect(saveWeight(client, 85.5, { override: false })).rejects.toThrow('Failed to fetch')

    expect(weightOf(client)).toBe(86.1)
  })

  it('takes it back too when the answer is an error body instead of a row', async () => {
    const client = clientWithToday()
    POST.mockResolvedValue({ data: undefined, error: { error: 'not_found' } })

    await expect(saveWeight(client, 85.5, { override: false })).rejects.toThrow()

    expect(weightOf(client)).toBe(86.1)
  })

  it('offers Undo, which deletes the row it made and asks the server again', async () => {
    const client = clientWithToday()
    POST.mockResolvedValue({ data: { id: 7, created: true } })
    DELETE.mockResolvedValue({ data: undefined, response: { status: 204 } })

    const { undo } = await saveWeight(client, 85.5, { override: false })
    client.setQueryData(todayQuery.queryKey, sampleTodayView())
    await undo?.()

    expect(DELETE).toHaveBeenCalledExactlyOnceWith('/api/v1/weight/logs/{log_id}', {
      params: { path: { log_id: 7 } },
    })
    expect(client.getQueryState(todayQuery.queryKey)?.isInvalidated).toBe(true)
  })

  it('offers no Undo for a reading that was already there', async () => {
    const client = clientWithToday()
    POST.mockResolvedValue({ data: { id: 3, created: false } })

    const { undo } = await saveWeight(client, 86.1, { override: false })

    expect(undo).toBeUndefined()
  })
})
