import { todayFixture } from '@/fixtures/today'
import type { TodayView } from './types'

/** The Today screen's data. Fixtures for now; the API (`GET /api/v1/today`) replaces the body
 *  of this hook and nothing else. */
export function useTodayView(): TodayView {
  return todayFixture
}
