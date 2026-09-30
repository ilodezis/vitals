import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { Markdown } from './markdown'

describe('Markdown', () => {
  it('escapes raw HTML tags such as img onerror and script as plain text', () => {
    const html = renderToStaticMarkup(
      <Markdown source={'<img src=x onerror=alert(1)> and <script>alert(1)</script>'} />,
    )

    expect(html).not.toContain('<img')
    expect(html).not.toContain('<script')
    expect(html).toBe(
      '<p>&lt;img src=x onerror=alert(1)&gt; and &lt;script&gt;alert(1)&lt;/script&gt;</p>',
    )
  })

  it('strips unsafe non-http link schemes and does not emit href', () => {
    const unsafeHtml = renderToStaticMarkup(
      <Markdown source={'[x](javascript:alert(1))'} />,
    )
    expect(unsafeHtml).not.toContain('href')
    expect(unsafeHtml).toBe('<p>x</p>')

    const safeHtml = renderToStaticMarkup(
      <Markdown source={'[docs](https://example.com/docs)'} />,
    )
    expect(safeHtml).toBe(
      '<p><a href="https://example.com/docs" rel="noopener noreferrer" target="_blank">docs</a></p>',
    )
  })

  it('renders headings, bold, italic, inline code, and lists', () => {
    const html = renderToStaticMarkup(
      <Markdown
        source={[
          '# Top',
          '## H',
          '### Sub',
          '',
          'Paragraph with **a** and *b* and `c`.',
          '',
          '- first',
          '- second',
          '',
          '1. one',
          '2. two',
        ].join('\n')}
      />,
    )

    expect(html).toContain('<h3>Top</h3>')
    expect(html).toContain('<h4>H</h4>')
    expect(html).toContain('<h5>Sub</h5>')
    expect(html).toContain('<strong>a</strong>')
    expect(html).toContain('<em>b</em>')
    expect(html).toContain('<span class="md-code">c</span>')
    expect(html).toContain('<ul><li>first</li><li>second</li></ul>')
    expect(html).toContain('<ol><li>one</li><li>two</li></ol>')
  })
})
