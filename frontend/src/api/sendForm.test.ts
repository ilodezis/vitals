import { afterEach, describe, expect, it, vi } from 'vitest'
import { RequestError } from './client'
import { sendForm } from './sendForm'

/** Just enough of XMLHttpRequest to drive the upload by hand. */
class FakeXhr {
  static last: FakeXhr
  status = 0
  upload: { onprogress: ((e: { lengthComputable: boolean; loaded: number; total: number }) => void) | null } = { onprogress: null }
  onload: (() => void) | null = null
  onerror: (() => void) | null = null
  onabort: (() => void) | null = null
  method = ''
  url = ''
  body: unknown = null
  constructor() {
    FakeXhr.last = this
  }
  open(method: string, url: string) {
    this.method = method
    this.url = url
  }
  send(body: unknown) {
    this.body = body
  }
}

describe('sendForm', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('posts the form and reports the share sent', async () => {
    vi.stubGlobal('XMLHttpRequest', FakeXhr)
    const seen: number[] = []
    const fd = new FormData()
    const done = sendForm('/api/v1/skincare/photos', fd, (s) => seen.push(s))
    const xhr = FakeXhr.last
    expect([xhr.method, xhr.url, xhr.body]).toEqual(['POST', '/api/v1/skincare/photos', fd])
    xhr.upload.onprogress?.({ lengthComputable: true, loaded: 25, total: 100 })
    xhr.upload.onprogress?.({ lengthComputable: false, loaded: 0, total: 0 })
    xhr.upload.onprogress?.({ lengthComputable: true, loaded: 100, total: 100 })
    xhr.status = 201
    xhr.onload?.()
    await expect(done).resolves.toBeUndefined()
    expect(seen).toEqual([0.25, 1])
  })

  it('throws the status of a refusal', async () => {
    vi.stubGlobal('XMLHttpRequest', FakeXhr)
    const done = sendForm('/api/v1/skincare/photos', new FormData(), () => {})
    FakeXhr.last.status = 413
    FakeXhr.last.onload?.()
    await expect(done).rejects.toEqual(new RequestError(413))
  })

  it('throws status 0 when the connection drops', async () => {
    vi.stubGlobal('XMLHttpRequest', FakeXhr)
    const done = sendForm('/api/v1/skincare/photos', new FormData(), () => {})
    FakeXhr.last.onerror?.()
    await expect(done).rejects.toMatchObject({ status: 0 })
  })
})
