import { describe, expect, it } from 'vitest'

/* `.btn` is the amber main button. A text button is `.ghost` alone: writing both makes an
   amber slab with a text button's label, and a screen ends up with five "main" buttons. */

const sources = import.meta.glob<string>(['/src/**/*.tsx', '!/src/**/*.test.tsx', '!/src/fixtures/**'], {
  query: '?raw',
  import: 'default',
  eager: true,
})

export function mixesBtnAndGhost(source: string): string[] {
  const found: string[] = []
  for (const match of source.matchAll(/className\s*=\s*(?:"([^"]*)"|\{`([^`]*)`\}|'([^']*)')/g)) {
    const tokens = (match[1] ?? match[2] ?? match[3] ?? '').split(/\s+/)
    if (tokens.includes('btn') && tokens.includes('ghost')) found.push(match[0])
  }
  return found
}

describe('mixesBtnAndGhost', () => {
  it('finds a text button that also carries the main-button class', () => {
    expect(mixesBtnAndGhost('<button className="btn ghost danger">')).toHaveLength(1)
    expect(mixesBtnAndGhost('<button className="ghost danger">')).toHaveLength(0)
    expect(mixesBtnAndGhost('<button className="btn grow">')).toHaveLength(0)
  })
})

describe('button classes', () => {
  it('never pairs .btn with .ghost', () => {
    const offenders = Object.entries(sources).flatMap(([file, text]) => mixesBtnAndGhost(text).map((m) => `${file}: ${m}`))
    expect(offenders).toEqual([])
  })
})
