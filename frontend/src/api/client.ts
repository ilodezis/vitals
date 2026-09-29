import createClient, { type ClientOptions, type Middleware } from 'openapi-fetch'
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
      // The session ended (or never was). The login form sends the user back here.
      const next = location.pathname + location.search
      location.assign(`/login?next=${encodeURIComponent(next)}`)
    } else if (response.status === 409) {
      throw new ConflictError(await violationsOf(response))
    }
    // Everything else — 400 invalid, 404 module_disabled / not_found, 422 — comes
    // back as `{ error }` for the caller to show.
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
