import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { I18nProvider } from '@/i18n/I18nProvider'
import { DataSection, pressRestart } from './DataSection'

const DICTIONARY = {
  'settings.restart_title': 'Container restart',
  'settings.restart_hint': 'Restarts the container.',
  'settings.restart_text': 'Restarting the app…',
  'settings.restart_btn': 'Restart container',
  'common.confirm_question': 'Sure?',
}

function render() {
  return renderToStaticMarkup(
    <QueryClientProvider client={new QueryClient()}>
      <I18nProvider lang="en" dictionary={DICTIONARY}>
        <DataSection />
      </I18nProvider>
    </QueryClientProvider>,
  )
}

describe('restart step', () => {
  it('asks first, restarts on the second press, and ignores presses while it runs', () => {
    expect(pressRestart('idle')).toEqual({ phase: 'confirm', fire: false })
    expect(pressRestart('confirm')).toEqual({ phase: 'restarting', fire: true })
    expect(pressRestart('restarting')).toEqual({ phase: 'restarting', fire: false })
  })
})

describe('DataSection', () => {
  it('describes the restart instead of claiming one is running', () => {
    const html = render()
    expect(html).toContain('Restarts the container.')
    expect(html).not.toContain('Restarting the app')
  })

  it('keeps the secondary actions off the amber button style', () => {
    expect(render()).not.toMatch(/class="([^"]* )?btn( [^"]*)?"/)
  })
})
