import createClient, { type ClientOptions, type Middleware } from 'openapi-fetch'
import { persister } from '@/app/persist'
import type { components, paths } from './schema'

export type Violation = components['schemas']['ViolationBody']

/** A write the conflict engine blocked (409). Repeat it with `override: true` to
 *  keep it anyway; `violations` are the rules it tripped, in the user's language. */
export class ConflictError extends Error {
  readonly violations: Violation[]

  constructor(violations: Violation[]) {
    super(violations.map((v) => v.message).join('; '))
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

/** The message of a 400 that came without one: a marker for the code, never shown. */
const UNEXPLAINED = 'Invalid'

/** A request the server did not carry out for any other reason (5xx, 404, 422, no network).
 *  It has no words for the user: the screen says what failed in its own language. */
export class RequestError extends Error {
  readonly status: number

  constructor(status: number) {
    super(`Request failed (${status})`)
    this.name = 'RequestError'
    this.status = status
  }
}

/** The data of a call, or a throw: a response the server refused is never taken for a
 *  success. `openapi-fetch` hands a refusal back as `{ error }` and would otherwise let a
 *  "Saved" toast follow a 500. */
export async function ok<T>(call: Promise<{ data?: T; error?: unknown; response: Response }>): Promise<T> {
  const { data, error, response } = await call
  if (error !== undefined || response.status >= 400) throw new RequestError(response.status)
  return data as T
}

/** What to tell the user about a failed write: the service's own words when it explained
 *  itself (400, 409 — already in the user's language), otherwise the screen's `fallback`.
 *  A raw exception text never reaches the screen. */
export function failText(error: unknown, fallback: string): string {
  const explained = error instanceof InvalidError || error instanceof ConflictError
  return explained && error.message !== '' && error.message !== UNEXPLAINED ? error.message : fallback
}

async function messageOf(response: Response): Promise<string> {
  try {
    const body: unknown = await response.clone().json()
    const message = (body as Partial<components['schemas']['InvalidBody']> | null)?.message
    return typeof message === 'string' && message !== '' ? message : UNEXPLAINED
  } catch {
    return UNEXPLAINED
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
