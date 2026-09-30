import { RequestError } from '@/api/client'
import type { components } from '@/api/schema'

export type LabPreview = components['schemas']['LabExtractedPreview']

/** What one file of the queue came back as: markers to check, a failure to report and move past,
 *  or a stop — recognition is not set up, and every other file would fail the same way. */
export type UploadOutcome = { kind: 'preview'; lab: LabPreview } | { kind: 'failed'; reason: string } | { kind: 'stop'; reason: string }

/** Send one file to be read. A refused request is a failure of this file, never of the queue. */
export async function uploadLabFile(file: File, fallback: string): Promise<UploadOutcome> {
  try {
    const fd = new FormData()
    fd.append('file', file)
    const res = await fetch('/api/v1/labs/upload', { method: 'POST', body: fd, credentials: 'same-origin' })
    if (!res.ok) throw new RequestError(res.status)
    const data = (await res.json()) as components['schemas']['LabUploadResponse']
    if (data.ok && data.lab) return { kind: 'preview', lab: data.lab }
    const reason = data.message || fallback
    return data.reason === 'not_configured' ? { kind: 'stop', reason } : { kind: 'failed', reason }
  } catch {
    return { kind: 'failed', reason: fallback }
  }
}

/** The running tally of a queue: markers saved, and each file that failed with why. */
export interface QueueTally {
  added: number
  errors: string[]
}

/** "scan.jpg — could not read it": which file to re-shoot, and why. */
export const failureLine = (fileName: string, reason: string): string => (fileName === '' ? reason : `${fileName} — ${reason}`)

/** Whether anything happened worth a summary: skipping every file says nothing. */
export const hasSummary = (tally: QueueTally): boolean => tally.added > 0 || tally.errors.length > 0
