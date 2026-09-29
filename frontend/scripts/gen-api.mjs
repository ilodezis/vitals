// src/api/openapi.json -> src/api/schema.d.ts, the types behind the API client.
//
// openapi-typescript 7 does not install next to TypeScript 7 (its peer is ^5), so
// it runs through npx with its own pinned TypeScript instead of living in
// package.json. Its output is stamped with a hash of the schema it read: the
// backend test suite (tests/test_api_contract.py) has no Node, and the stamp is
// how it notices a schema that was regenerated without its types.
import { execSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import { appendFileSync, readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
const source = resolve(root, 'src/api/openapi.json')
const target = resolve(root, 'src/api/schema.d.ts')

execSync(
  'npx --yes -p typescript@5.9.3 -p openapi-typescript@7.13.0 openapi-typescript "' +
    source +
    '" -o "' +
    target +
    '"',
  { stdio: 'inherit', cwd: root },
)

// Hashed as LF text so a CRLF checkout of the schema stamps the same way.
const text = readFileSync(source, 'utf8').replace(/\r\n/g, '\n')
const hash = createHash('sha256').update(text, 'utf8').digest('hex')
appendFileSync(target, `\n// openapi.json sha256: ${hash}\n`)
