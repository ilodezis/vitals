// Startup budget: the JavaScript a cold visit has to download before the app can
// draw anything — the entry chunk plus everything it imports statically. Route
// chunks load lazily on navigation and are not counted. Exits 1 over budget.
import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { gzipSync } from 'node:zlib'

const BUDGET_BYTES = 150 * 1024

const outDir = fileURLToPath(new URL('../../web/static/app/', import.meta.url))
const manifestPath = join(outDir, '.vite', 'manifest.json')

if (!existsSync(manifestPath)) {
  console.error(`check-size: no build manifest at ${manifestPath} — run the build first`)
  process.exit(1)
}

const manifest = JSON.parse(readFileSync(manifestPath, 'utf8'))
const entries = Object.keys(manifest).filter((key) => manifest[key].isEntry)
if (entries.length !== 1) {
  console.error(`check-size: expected one entry chunk, found ${entries.length}`)
  process.exit(1)
}

const seen = new Set()
const files = []
const walk = (key) => {
  if (seen.has(key)) return
  seen.add(key)
  const chunk = manifest[key]
  files.push(chunk.file)
  for (const dep of chunk.imports ?? []) walk(dep)
}
walk(entries[0])

const kb = (bytes) => `${(bytes / 1024).toFixed(1)} KB`
let total = 0
for (const file of files) {
  const gz = gzipSync(readFileSync(join(outDir, file))).length
  total += gz
  console.log(`  ${kb(gz).padStart(9)}  ${file}`)
}

const verdict = total <= BUDGET_BYTES ? 'ok' : 'OVER BUDGET'
console.log(`startup JS (gzip): ${kb(total)} of ${kb(BUDGET_BYTES)} — ${verdict}`)
if (total > BUDGET_BYTES) process.exit(1)
