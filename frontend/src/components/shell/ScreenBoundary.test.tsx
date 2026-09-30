import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'
import { I18nProvider } from '@/i18n/I18nProvider'
import en from '@/i18n/en.json'
import { Catch, FailedNotice } from './ScreenBoundary'

/* There is no DOM here to throw a screen in, so the boundary is driven the way React drives it: a
   throw in a child reaches `getDerivedStateFromError`, whose answer becomes the state, and the next
   render is the fallback. What is checked is what the user is left with. */

const inEnglish = (node: React.ReactNode) =>
  renderToStaticMarkup(
    <I18nProvider lang="en" dictionary={en}>
      {node}
    </I18nProvider>,
  ).replaceAll('&#x27;', "'")

function boundary(onReset = vi.fn()) {
  const instance = new Catch({
    onReset,
    fallback: (retry) => <FailedNotice onRetry={retry} />,
    children: <p>the screen</p>,
  })
  // React would apply the state; here it is applied by hand.
  instance.setState = ((next: { failed: boolean }) => {
    instance.state = { ...instance.state, ...next }
  }) as typeof instance.setState
  return { instance, onReset }
}

describe('ScreenBoundary', () => {
  it('shows the screen while it reads fine', () => {
    const { instance } = boundary()

    expect(inEnglish(instance.render())).toBe('<p>the screen</p>')
  })

  it('takes a screen that threw and puts a failure notice with a retry button in its place', () => {
    const { instance } = boundary()

    instance.state = { ...instance.state, ...Catch.getDerivedStateFromError() }
    const html = inEnglish(instance.render())

    expect(html).not.toContain('the screen')
    expect(html).toContain('role="alert"')
    expect(html).toContain(en['app.load_failed'])
    expect(html).toContain(en['app.retry'])
    expect(html).toContain('<button')
  })

  it('tells the failed queries to run again, then draws the screen anew', () => {
    const { instance, onReset } = boundary()
    instance.state = { ...instance.state, ...Catch.getDerivedStateFromError() }

    instance.retry()

    expect(onReset).toHaveBeenCalledOnce()
    expect(inEnglish(instance.render())).toBe('<p>the screen</p>')
  })
})

describe('FailedNotice', () => {
  it('says what happened in the user’s language and offers the one action', () => {
    const ru = { 'app.load_failed': 'Не удалось загрузить экран', 'app.load_failed_sub': 'Ничего не изменилось.', 'app.retry': 'Повторить' }
    const html = renderToStaticMarkup(
      <I18nProvider lang="ru" dictionary={ru}>
        <FailedNotice onRetry={() => undefined} />
      </I18nProvider>,
    )

    expect(html).toContain('Не удалось загрузить экран')
    expect(html).toContain('Повторить')
  })
})
