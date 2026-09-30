import { describe, expect, it } from 'vitest'
import source from './sw.ts?raw'

describe('the service worker and private files', () => {
  it('never caches uploads or the API: both go to the network every time', () => {
    expect(source).toContain('registerRoute(/^\\/static\\/uploads\\/.*/i, new NetworkOnly())')
    expect(source).toContain('registerRoute(/^\\/api\\/.*/i, new NetworkOnly())')
  })

  it('does not answer uploads or the API with the app shell', () => {
    expect(source).toContain('denylist: [/^\\/api/, /^\\/static\\/uploads/]')
  })
})
