import { describe, expect, it } from 'vitest'
import openapi from './openapi.json'

/* The typed client cannot call a path the API does not have: it does not compile. A plain
   `fetch('/api/v1/…')` — a file download, a multipart upload — is only a string, and a wrong one
   answers 404 at run time. Every such string has to be a path of the committed schema. */

const sources = import.meta.glob<string>(['/src/**/*.{ts,tsx}', '!/src/**/*.test.{ts,tsx}', '!/src/**/*.d.ts'], {
  query: '?raw',
  import: 'default',
  eager: true,
})

const RAW_FETCH = /\bfetch\(\s*(['"`])(\/api\/v1\/[^'"`]*)\1/g

export function rawFetchPaths(source: string): string[] {
  return [...source.matchAll(RAW_FETCH)].map((m) => m[2] as string)
}

/** `/api/v1/labs/${id}/file` and `/api/v1/labs/{lab_id}/file` are the same path. */
const shapeOf = (path: string): string => path.replace(/\$\{[^}]*\}|\{[^}]*\}/g, '{}').replace(/\?.*$/, '')

describe('rawFetchPaths', () => {
  it('finds the path of a plain fetch however it is quoted', () => {
    expect(rawFetchPaths("await fetch('/api/v1/a/b', {})")).toEqual(['/api/v1/a/b'])
    expect(rawFetchPaths('fetch(`/api/v1/a/${id}`)')).toEqual(['/api/v1/a/${id}'])
  })

  it('leaves the typed client and other hosts alone', () => {
    expect(rawFetchPaths("api.GET('/api/v1/a'); fetch('/static/x.json')")).toEqual([])
  })
})

describe('plain fetch calls', () => {
  const known = new Set(Object.keys(openapi.paths).map(shapeOf))
  const used = Object.entries(sources).flatMap(([file, text]) => rawFetchPaths(text).map((path) => ({ file, path })))

  it('actually scans the source', () => {
    expect(used.length).toBeGreaterThan(3)
  })

  it('only ask for paths the API has', () => {
    const unknown = used.filter((u) => !known.has(shapeOf(u.path))).map((u) => `${u.file}: ${u.path}`)
    expect(unknown).toEqual([])
  })
})
