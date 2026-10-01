import { describe, expect, it, vi } from 'vitest'

const More = () => <p>more</p>
const Share = () => <p>share</p>
vi.mock('@/features/more/MoreScreen', () => ({ default: More }))
vi.mock('@/features/share/ShareScreen', () => ({ default: Share }))

const { preloadScreen, screenComponent } = await import('./screens')

describe('screenComponent', () => {
  it('hands out the screen itself once its code has arrived, not a lazy shell that draws empty first', async () => {
    await preloadScreen('more')
    expect(screenComponent('more')).toBe(More)
  })

  it('keeps one component per screen for its whole life, even if the code arrives later', async () => {
    const early = screenComponent('share')
    await preloadScreen('share')
    expect(screenComponent('share')).toBe(early)
  })
})
