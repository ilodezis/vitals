import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { I18nProvider } from '@/i18n/I18nProvider'
import { PhotosPane, uploadStatus } from './PhotosPane'
import type { SkincareView } from './types'

describe('uploadStatus', () => {
  it('counts the bytes sent, then waits for the server', () => {
    expect(uploadStatus(0)).toEqual({ pct: 0, saving: false })
    expect(uploadStatus(0.426)).toEqual({ pct: 43, saving: false })
    expect(uploadStatus(1)).toEqual({ pct: 100, saving: true })
  })
})

describe('PhotosPane', () => {
  it('offers the upload, idle, before anything is chosen', () => {
    const view = { today: '2026-10-22', photos: [] } as unknown as SkincareView
    const html = renderToStaticMarkup(
      <QueryClientProvider client={new QueryClient()}>
        <I18nProvider lang="en" dictionary={{ 'app.skincare.photo_upload': 'Upload photos' }}>
          <PhotosPane view={view} />
        </I18nProvider>
      </QueryClientProvider>,
    )
    expect(html).toContain('Upload photos')
    expect(html).toContain('aria-busy="false"')
  })
})
