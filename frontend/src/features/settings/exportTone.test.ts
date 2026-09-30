import { describe, expect, it } from 'vitest'
import { exportTone } from './ConnectionsSection'

describe('Garmin weight export tone', () => {
  it('warns about a stuck or refused export, notes an empty queue, and plainly reports the rest', () => {
    expect(exportTone('failed')).toBe('warn')
    expect(exportTone('delete_failed')).toBe('warn')
    expect(exportTone(null)).toBe('note')
    expect(exportTone('skipped')).toBe('note')
    expect(exportTone('sent')).toBe('info')
    expect(exportTone('pending')).toBe('info')
  })
})
