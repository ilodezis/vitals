import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { I18nProvider } from './I18nProvider'
import { loadDictionary } from './load'
import { useT } from './useT'

function Probe() {
  const { t, plural, lang } = useT()
  return (
    <p>
      {lang}|{t('nav.weight')}|{t('sync.days_ago', { n: 5, word: plural(5, 'день', 'дня', 'дней') })}
    </p>
  )
}

describe('useT', () => {
  it('translates and pluralises in the provider’s language', () => {
    const html = renderToStaticMarkup(
      <I18nProvider
        lang="ru"
        dictionary={{ 'nav.weight': 'Вес', 'sync.days_ago': '{n} {word} назад' }}
      >
        <Probe />
      </I18nProvider>,
    )

    expect(html).toBe('<p>ru|Вес|5 дней назад</p>')
  })

  it('refuses to run outside a provider', () => {
    expect(() => renderToStaticMarkup(<Probe />)).toThrow(/I18nProvider/)
  })
})

describe('loadDictionary', () => {
  it('loads the exported dictionary of each language', async () => {
    const en = await loadDictionary('en')
    const ru = await loadDictionary('ru')

    expect(en['nav.weight']).toBe('Weight')
    expect(ru['nav.weight']).toBe('Вес')
    expect(Object.keys(ru).sort()).toEqual(Object.keys(en).sort())
  })
})
