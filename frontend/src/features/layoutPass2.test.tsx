import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { Odometer } from '@/components/controls/Odometer'
import appCss from '@/styles/app.css?raw'
import todayCss from '@/features/today/today.css?raw'
import glp1Css from '@/features/glp1/glp1.css?raw'
import geneticsCss from '@/features/genetics/genetics.css?raw'
import reportsCss from '@/features/reports/reports.css?raw'
import shareCss from '@/features/share/share.css?raw'
import shareScreenSrc from '@/features/share/ShareScreen.tsx?raw'
import reportsScreenSrc from '@/features/reports/ReportsScreen.tsx?raw'
import logSheetSrc from '@/components/sheet/LogSheet.tsx?raw'
import todayScreenSrc from '@/features/today/TodayScreen.tsx?raw'

describe('Pass 2 layout guards', () => {
  it('U2: Odometer renders data-digit on reels and app.css centers digits with tabular-nums', () => {
    const html = renderToStaticMarkup(<Odometer value="10,0" />)
    expect(html).toContain('data-digit="1"')
    expect(html).toContain('data-digit="0"')

    // CSS checks
    expect(appCss).toMatch(/\.odo\s*\{[^}]*tabular-nums/)
    expect(appCss).toMatch(/\.odo-d\s*\{[^}]*text-align:\s*center/)
    expect(appCss).toMatch(/\.odo-s\s*>\s*span\s*\{[^}]*text-align:\s*center/)
  })

  it('U3: today.css defines a 4-column equal grid for quick chips in today-log', () => {
    expect(todayCss).toMatch(/\.today-log\s+\.qchips\s*\{[^}]*grid-template-columns:\s*repeat\(4,\s*minmax\(0,\s*1fr\)\)/)
    expect(todayCss).toMatch(/\.today-log\s+\.qchips\s*\{[^}]*width:\s*100%/)
  })

  it('U4: collapse is hidden when not open, LogSheet has no artificial spacer, and opts have no negative margin', () => {
    expect(appCss).toMatch(/\.collapse:not\(\.open\)\s*\{\s*display:\s*none;\s*\}/)
    expect(logSheetSrc).not.toMatch(/style=\{\{\s*height:\s*6\s*\}\}/)
    expect(appCss).toMatch(/\.opts\s*\{[^}]*margin:\s*0/)
    expect(appCss).not.toMatch(/\.opts\s*\{[^}]*margin:\s*0\s+-13px/)
  })

  it('U5: feed rows omit time span and use no-time class when row.time is empty, and feed has border', () => {
    expect(todayScreenSrc).toMatch(/hasTime\s*&&\s*<span className="time">/)
    expect(todayScreenSrc).toMatch(/!hasTime\s*&&\s*'no-time'/)
    expect(todayCss).toMatch(/\.feed\s*\{[^}]*border-top:\s*1px solid var\(--line\)/)
    expect(todayCss).toMatch(/\.feed-row\.no-time\s*\{\s*grid-template-columns:\s*16px 1fr;\s*\}/)
  })

  it('U6: GLP-1 cycle has spacing and no hardcoded 25% progress width in CSS', () => {
    expect(glp1Css).toMatch(/\.cycle\s*\{[^}]*margin-bottom:\s*8px/)
    expect(glp1Css).not.toMatch(/\.cycle\s+\.prog\s*\{[^}]*width:\s*25%/)
  })

  it('U7: Genetics filters align to page column without negative margin', () => {
    expect(geneticsCss).toMatch(/\.gen-filter-wrap\s+\.filters\s*\{[^}]*margin:\s*0;\s*padding:\s*0/)
    expect(appCss).toMatch(/\.filters\s*\{[^}]*margin:\s*var\(--s5\)\s+0\s+0\s+0/)
  })

  it('U8: ReportsScreen uses standard grid and digest takes full column width without rep-grid conflict', () => {
    expect(reportsScreenSrc).not.toMatch(/<div className="rep-grid">/)
    expect(reportsScreenSrc).toMatch(/<div className="grid">/)
    expect(reportsCss).not.toMatch(/grid-template-columns:\s*5fr 7fr/)
    expect(reportsCss).toMatch(/\.digest\s*\{[^}]*width:\s*100%/)
  })

  it('U9: ShareScreen aligns period and expiry in two columns and lab toggle flabel does not duplicate option', () => {
    expect(shareScreenSrc).toMatch(/<div className="share-grid-2">/)
    expect(shareScreenSrc).toMatch(/t\('share\.section\.labs'\)/)
    expect(shareCss).toMatch(/@container app \(min-width:\s*768px\)\s*\{[^}]*\.share-grid-2\s*\{[^}]*grid-template-columns:\s*repeat\(2/)
  })
})
