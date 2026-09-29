import createClient, { type ClientOptions, type Middleware } from 'openapi-fetch'
import { persister } from '@/app/persist'
import type { components, paths } from './schema'

export type Violation = components['schemas']['ViolationBody']

/** A write the conflict engine blocked (409). Repeat it with `override: true` to
 *  keep it anyway; `violations` are the rules it tripped, in the user's language. */
export class ConflictError extends Error {
  readonly violations: Violation[]

  constructor(violations: Violation[]) {
    super(violations.map((v) => v.message).join('; ') || 'Conflict')
    this.name = 'ConflictError'
    this.violations = violations
  }
}

/** A write the service refused (400): the values are wrong, and `message` says how, in the
 *  service's own words. Nothing was saved. */
export class InvalidError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'InvalidError'
  }
}

async function messageOf(response: Response): Promise<string> {
  try {
    const body: unknown = await response.clone().json()
    const message = (body as Partial<components['schemas']['InvalidBody']> | null)?.message
    return typeof message === 'string' && message !== '' ? message : 'Invalid'
  } catch {
    return 'Invalid'
  }
}

async function violationsOf(response: Response): Promise<Violation[]> {
  try {
    const body: unknown = await response.clone().json()
    const list = (body as Partial<components['schemas']['ConflictBody']> | null)?.violations
    return Array.isArray(list) ? list : []
  } catch {
    return []
  }
}

const sessionAndConflicts: Middleware = {
  async onResponse({ response }) {
    if (response.status === 401) {
      // The session ended (or never was). What the device kept of the last one goes with it; the
      // login form sends the user back here.
      void persister.removeClient()
      const next = location.pathname + location.search
      location.assign(`/login?next=${encodeURIComponent(next)}`)
    } else if (response.status === 409) {
      throw new ConflictError(await violationsOf(response))
    } else if (response.status === 400) {
      throw new InvalidError(await messageOf(response))
    }
    // Everything else — 404 module_disabled / not_found, 422 — comes back as `{ error }` for
    // the caller to show.
  },
}

/** The typed client for `/api/v1`. The cookie rides along because the API is on
 *  the app's own origin; the server's origin check lets same-origin fetches in. */
export function createApiClient(options: ClientOptions = {}) {
  const client = createClient<paths>({ credentials: 'same-origin', ...options })
  client.use(sessionAndConflicts)
  return client
}

export const api = createApiClient()
