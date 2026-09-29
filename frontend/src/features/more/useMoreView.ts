import { moreStatusFixture, moreSystemFixture, type MoreStatus } from '@/fixtures/more'

export interface MoreView {
  /** A short status per section, keyed by module key. */
  status: Record<string, MoreStatus>
  system: Record<'share' | 'settings', MoreStatus>
}

/** The More screen's statuses. Fixtures for now; the API replaces the body. */
export function useMoreView(): MoreView {
  return { status: moreStatusFixture, system: moreSystemFixture }
}
