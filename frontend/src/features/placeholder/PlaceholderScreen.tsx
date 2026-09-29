import { Icon } from '@/components/icons/Icon'
import { Headline, Mast, TopBar } from '@/components/shell/PageHead'
import { SCREEN_TITLE_KEY } from '@/components/shell/nav'
import { useScreen } from '@/components/shell/ScreenFrame'
import { useT } from '@/i18n/useT'

/** Stands in for a section that has not moved to the new app yet: its name, and one line saying so. */
export default function PlaceholderScreen() {
  const { t } = useT()
  const { id } = useScreen()
  const title = t(SCREEN_TITLE_KEY[id])
  return (
    <>
      <TopBar title={title} />
      <Mast screen={id} />
      <Headline title={title} />
      <div className="st-body">
        <div className="empty">
          <Icon name="info" />
          <p>
            {t('app.soon')}
            <small>{t('app.soon_sub')}</small>
          </p>
        </div>
      </div>
    </>
  )
}
