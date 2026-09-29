import { glp1Fixture } from '@/fixtures/glp1'
import type { Glp1View } from './types'

/** The GLP-1 screen's data. Fixtures for now; `GET /api/v1/glp1` replaces the body. */
export function useGlp1View(): Glp1View {
  return glp1Fixture
}
