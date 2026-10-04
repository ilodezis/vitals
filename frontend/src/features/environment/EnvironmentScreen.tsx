import { useRef } from 'react'
import { useTodayIso } from '@/app/session'
import { Icon } from '@/components/icons/Icon'
import { Headline, Mast, TopBar } from '@/components/shell/PageHead'
import { ScreenLink } from '@/components/shell/navigation'
import { useT } from '@/i18n/useT'
import { useNowMs } from '@/lib/useNowMs'
import { useOnScreen } from '@/lib/useOnScreen'
import { LIVE_REFETCH_MS } from './environmentApi'
import { NightSection } from './NightSection'
import { NowSection } from './NowSection'
import { TodaySection } from './TodaySection'
import { useEnvironmentLive } from './useEnvironmentView'
import './environment.css'

/** A reading older than this many polls on this device has stopped being kept current. */
const AWAY_AFTER_MS = LIVE_REFETCH_MS * 5

export default function EnvironmentScreen() {
  const { t } = useT()
  const body = useRef<HTMLDivElement>(null)
  const inView = useOnScreen(body)
  const todayIso = useTodayIso()
  const live = useEnvironmentLive(inView)
  const nowMs = useNowMs(1000, inView)

  const { data, dataUpdatedAt } = live
  // Past its time and not being renewed (or being renewed and failing): say so, do not pass it off as live.
  const vitalsAway = nowMs - dataUpdatedAt > AWAY_AFTER_MS && (!live.isFetching || live.isRefetchError)

  return (
    <>
      <TopBar title={t('nav.environment')} />
      <Mast screen="environment" />
      <Headline title={t('nav.environment')} />
      <p className="sub lede">{t('app.env.lede')}</p>

      <div ref={body} className="env">
        {!data.configured || data.station.status === 'never' ? (
          <section className="sec env-empty">
            <Icon name="air" />
            <h2>{t(data.configured ? 'app.env.waiting.title' : 'app.env.empty.title')}</h2>
            <p>{t(data.configured ? 'app.env.waiting.body' : 'app.env.empty.body')}</p>
            <ScreenLink screen="settings" className="ghost">
              <Icon name="sliders" />
              <span>{t('app.env.empty.action')}</span>
            </ScreenLink>
          </section>
        ) : (
          <>
            <NowSection live={data} answeredAt={dataUpdatedAt} nowMs={nowMs} vitalsAway={vitalsAway} />
            <TodaySection thresholds={data.thresholds} inView={inView} />
            <NightSection date={todayIso} thresholds={data.thresholds} />
          </>
        )}
      </div>
    </>
  )
}
