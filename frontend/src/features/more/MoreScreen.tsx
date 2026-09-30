import { logOut } from '@/app/logout'
import { useSession } from '@/app/session'
import { TextButton } from '@/components/controls/Marks'
import { Icon } from '@/components/icons/Icon'
import { ScreenLink } from '@/components/shell/navigation'
import { TopBar } from '@/components/shell/PageHead'
import { rubricsOf, SCREEN_TITLE_KEY } from '@/components/shell/nav'
import { useT } from '@/i18n/useT'
import { cx } from '@/lib/cx'
import { useMoreView } from './useMoreView'
import './more.css'

/** Phone only: every section, grouped by rubric, each with a one-phrase status. */
export default function MoreScreen() {
  const { t } = useT()
  const session = useSession()
  const view = useMoreView()
  const rubrics = rubricsOf(session.nav.items)

  return (
    <>
      <TopBar title={t('nav.more')} />
      <div className="kicker more-kicker">{t('app.more.all')}</div>
      <h1 className="h1">{t('nav.more')}</h1>
      {rubrics.map((rubric) => (
        <section key={rubric.id} className="more-group">
          <h2>{t(`masthead.rubric.${rubric.id}`)}</h2>
          <div className="more-list">
            {rubric.sections.map((s) => {
              const status = view.status[s.key]
              return (
                <ScreenLink key={s.key} screen={s.screen} mode="push" className="more-row">
                  <span className="mi">
                    <Icon name={s.icon} />
                  </span>
                  <span className="t">{t(SCREEN_TITLE_KEY[s.screen])}</span>
                  <span className={cx('s', status?.tone)}>{status?.text ?? ''}</span>
                  <Icon name="chevR" className="chev" />
                </ScreenLink>
              )
            })}
          </div>
        </section>
      ))}
      <section className="more-group">
        <h2>{t('app.system')}</h2>
        <div className="more-list">
          <ScreenLink screen="share" mode="push" className="more-row">
            <span className="mi">
              <Icon name="clipboard" />
            </span>
            <span className="t">{t('app.nav.share')}</span>
            <span className="s">{view.system.share.text}</span>
            <Icon name="chevR" className="chev" />
          </ScreenLink>
          <ScreenLink screen="settings" mode="push" className="more-row">
            <span className="mi">
              <Icon name="sliders" />
            </span>
            <span className="t">{t('nav.settings')}</span>
            <span className="s">{view.system.settings.text}</span>
            <Icon name="chevR" className="chev" />
          </ScreenLink>
        </div>
      </section>
      <div className="more-out">
        <TextButton icon="lock" onClick={() => void logOut()}>
          {t('nav.logout')}
        </TextButton>
      </div>
    </>
  )
}
