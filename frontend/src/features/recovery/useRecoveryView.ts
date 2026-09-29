import { recoveryFixture } from '@/fixtures/recovery'
import type { RecoveryView } from './types'

/** The Recovery screen's data. Fixtures for now; `GET /api/v1/recovery` replaces the body. */
export function useRecoveryView(): RecoveryView {
  return recoveryFixture
}
