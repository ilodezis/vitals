import type { ReactNode } from 'react'
import { SectionTabs } from '@/components/controls/SectionTabs'
import { Icon } from '@/components/icons/Icon'
import { useSession } from '@/app/session'
import { useT } from '@/i18n/useT'
import { hrefOf, useBack, useGo } from './navigation'
import { navScreen, rubricOfScreen, rubricsOf, SCREEN_TITLE_KEY, type ScreenId } from './nav'
import { preloadScreen } from './screens'
import { useScreen } from './ScreenFrame'

/** The bar at the top of a phone screen: back with the previous screen's name, the compact
 *  title that fades in as the large one scrolls away, and room for an action. */
export function TopBar({ title, right }: { title: string; right?: ReactNode }) {
  const { t } = useT()
  const { back } = useScreen()
  const goBack = useBack()
  return (
    <div className="topbar">
      <div className="topbar-l">
        {back !== null && (
          <button type="button" className="back" onClick={() => goBack()}>
            <Icon name="chevL" />
            <span>{t(SCREEN_TITLE_KEY[back])}</span>
          </button>
        )}
      </div>
      <div className="topbar-title">{title}</div>
      <div className="topbar-r">{right}</div>
    </div>
  )
}

/** "Where you are": the rubric's name, the section's siblings as underlined tabs, and the
 *  screen's actions at the right on a desktop. `sub` is a second level of tabs. */
export function Mast({ screen, actions, sub }: { screen: ScreenId; actions?: ReactNode; sub?: ReactNode }) {
  const { t } = useT()
  const session = useSession()
  const go = useGo()
  const rubrics = rubricsOf(session.nav.items)
  const rubric = rubricOfScreen(screen, rubrics)
  const active = navScreen(screen)

  return (
    <header className="mast">
      <div className="kicker">
        <span className="crumb">{rubric === undefined ? t('app.system') : t(`masthead.rubric.${rubric.id}`)}</span>
      </div>
      <div className="mast-actions">{actions}</div>
      {rubric !== undefined && (
        <SectionTabs
          items={rubric.sections.map((s) => ({ id: s.screen, label: t(`nav.${s.key}`), href: hrefOf(s.screen) }))}
          active={active}
          onSelect={(id) => go(id as ScreenId, { mode: 'replace' })}
          onPreload={(id) => void preloadScreen(id as ScreenId)}
        />
      )}
      {sub}
    </header>
  )
}

/** The big title, and beside it (on a desktop) the screen's key figures. */
export function Headline({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="headline">
      <h1 className="h1">{title}</h1>
      {children}
    </div>
  )
}
