import { weightFixture } from '@/fixtures/weight'
import type { WeightView } from './types'

/** The Weight screen's data. Fixtures for now; `GET /api/v1/weight` replaces the body. */
export function useWeightView(): WeightView {
  return weightFixture
}
