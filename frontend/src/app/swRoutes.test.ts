import { describe, expect, it } from 'vitest'
import { APP_NAVIGATIONS } from './swRoutes'

const served = (path: string): boolean => APP_NAVIGATIONS.some((re) => re.test(path))

describe('the addresses the service worker serves the app shell for', () => {
  it.each(['/today', '/weight', '/weight/measures', '/recovery/sleep', '/recovery/sleep/2026-09-28', '/share', '/settings/'])(
    'answers %s',
    (path) => expect(served(path)).toBe(true),
  )

  it.each(['/login', '/logout', '/r/abc123', '/share/5/download', '/api/v1/session', '/static/app/sw.js', '/mcp', '/health', '/'])(
    'leaves %s to the network',
    (path) => expect(served(path)).toBe(false),
  )
})
