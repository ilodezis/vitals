import { afterEach, describe, expect, it, vi } from 'vitest'
import { failureLine, hasSummary, uploadLabFile } from './uploadQueue'

const file = new File(['x'], 'scan.jpg', { type: 'image/jpeg' })
const answer = (body: unknown, status = 200) => vi.fn(async () => new Response(JSON.stringify(body), { status }))

describe('uploadLabFile', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('hands back the recognized markers', async () => {
    vi.stubGlobal('fetch', answer({ ok: true, lab: { date: '2026-09-29', markers: [] } }))
    expect(await uploadLabFile(file, 'failed')).toEqual({ kind: 'preview', lab: { date: '2026-09-29', markers: [] } })
  })

  it('stops the queue when recognition is not set up', async () => {
    vi.stubGlobal('fetch', answer({ ok: false, reason: 'not_configured', message: 'No key' }))
    expect(await uploadLabFile(file, 'failed')).toEqual({ kind: 'stop', reason: 'No key' })
  })

  it('fails only this file when it could not be read or the request broke', async () => {
    vi.stubGlobal('fetch', answer({ ok: false, reason: 'error', message: 'Unreadable' }))
    expect(await uploadLabFile(file, 'failed')).toEqual({ kind: 'failed', reason: 'Unreadable' })
    vi.stubGlobal('fetch', answer({}, 500))
    expect(await uploadLabFile(file, 'failed')).toEqual({ kind: 'failed', reason: 'failed' })
  })
})

describe('queue summary', () => {
  it('names the file that failed', () => {
    expect(failureLine('scan.jpg', 'Unreadable')).toBe('scan.jpg — Unreadable')
  })

  it('says nothing when every file was skipped', () => {
    expect(hasSummary({ added: 0, errors: [] })).toBe(false)
    expect(hasSummary({ added: 3, errors: [] })).toBe(true)
    expect(hasSummary({ added: 0, errors: ['x'] })).toBe(true)
  })
})
