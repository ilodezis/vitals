import { labsFixture } from '@/fixtures/labs'
import type { LabsView } from './types'

/** The Labs screen's data. Fixtures for now; `GET /api/v1/labs` replaces the body. */
export function useLabsView(): LabsView {
  return labsFixture
}
