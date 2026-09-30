import { describe, expect, it, vi } from 'vitest'

const removeClient = vi.fn(async () => {})
vi.mock('./persist', () => ({ persister: { removeClient }, CACHE_MAX_AGE_MS: 1000 }))

const { queryClient } = await import('./queryClient')
const { restartInNewLanguage } = await import('./language')

describe('restartInNewLanguage', () => {
  it('drops what the device kept before the page reloads, so the old language cannot come back', async () => {
    queryClient.setQueryData(['session'], { lang: 'ru' })
    const order: string[] = []
    removeClient.mockImplementationOnce(async () => {
      order.push('forget')
    })
    await restartInNewLanguage(() => order.push('reload'))
    expect(queryClient.getQueryData(['session'])).toBeUndefined()
    expect(order).toEqual(['forget', 'reload'])
  })
})
