import { useLayoutEffect, useRef } from 'react'
import { useSession } from '@/app/session'
import { Icon } from '@/components/icons/Icon'
import { toggleLogSheet } from '@/components/sheet/logSheetStore'
import { useT } from '@/i18n/useT'
import { cx } from '@/lib/cx'
import { barTabs, rubricsOf, tabOf, type BarTab, type ScreenId } from './nav'
import { scrollCurrentToTop, useBack, useGo } from './navigation'
import { preloadScreen } from './screens'

const labelKey = (tab: BarTab): string =>
  tab.kind === 'today' ? 'nav.today' : tab.kind === 'more' ? 'nav.more' : `nav.tab.${tab.id}`

/** The phone's bottom bar: today, two rubrics, More — and the amber "+" that opens the log in
 *  the middle. The amber line slides to the tab the current stack belongs to. */
export function BottomNav({ root, depth }: { root: ScreenId; depth: number }) {
  const { t } = useT()
  const session = useSession()
  const go = useGo()
  const back = useBack()
  const bar = useRef<HTMLElement>(null)
  const rubrics = rubricsOf(session.nav.items)
  const { left, right } = barTabs(rubrics)
  const current = tabOf(root, rubrics, [...left, ...right])

  useLayoutEffect(() => {
    const el = bar.current
    if (el === null) return
    const place = () => {
      const on = el.querySelector<HTMLElement>('a.on')
      const ink = el.querySelector<HTMLElement>('.ink')
      if (on !== null && ink !== null) ink.style.transform = `translateX(${on.offsetLeft + on.offsetWidth / 2 - 10}px)`
    }
    place()
    const observer = new ResizeObserver(place)
    observer.observe(el)
    return () => observer.disconnect()
  }, [current])

  const tab = (item: BarTab) => (
    <a
      key={item.id}
      href="#"
      className={cx(item.id === current && 'on')}
      aria-current={item.id === current ? 'page' : undefined}
      onClick={(e) => {
        e.preventDefault()
        // Tapping the tab you are in goes back to its first screen; on the first, it scrolls up.
        if (item.id === current) {
          if (depth > 1) back(depth - 1)
          else scrollCurrentToTop()
          return
        }
        go(item.screen, { mode: 'tab' })
      }}
      onPointerEnter={() => void preloadScreen(item.screen)}
    >
      <Icon name={item.icon} />
      <span>{t(labelKey(item))}</span>
    </a>
  )

  return (
    <nav ref={bar} className="bnav">
      <i className="ink" />
      {left.map(tab)}
      <button type="button" className="plus" aria-label={t('app.log')} onClick={() => toggleLogSheet('weight')}>
        <Icon name="plus" />
      </button>
      {right.map(tab)}
    </nav>
  )
}
