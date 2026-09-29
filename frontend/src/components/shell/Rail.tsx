import { useLayoutEffect, useRef } from 'react'
import { useSession } from '@/app/session'
import { Icon } from '@/components/icons/Icon'
import { useT } from '@/i18n/useT'
import { cx } from '@/lib/cx'
import { formatNumber, formatSigned, type Lang } from '@/lib/format'
import { toggleLogSheet } from '@/components/sheet/logSheetStore'
import { BUILT_SCREENS, navScreen, rubricsOf, SCREEN_TITLE_KEY, type ScreenId, type SessionView } from './nav'
import { ScreenLink } from './navigation'

type RailStat = SessionView['rail'][number]

/** "7 h 34 min" from seconds. */
function duration(seconds: number, t: (key: string, p?: Record<string, string | number>) => string): string {
  const minutes = Math.round(seconds / 60)
  return t('app.duration.hm', { h: Math.floor(minutes / 60), m: String(minutes % 60).padStart(2, '0') })
}

function statRow(
  stat: RailStat,
  t: (key: string, p?: Record<string, string | number>) => string,
  lang: Lang,
): { label: string; value: string; note?: string; tone?: 'good' | 'bad' } | null {
  switch (stat.key) {
    case 'weight':
      if (stat.weight_kg === null) return null
      return {
        label: t('app.rail.weight'),
        value: formatNumber(stat.weight_kg, lang),
        note: stat.delta_kg === null ? undefined : t('app.rail.per_week', { value: formatSigned(stat.delta_kg, lang) }),
        tone: stat.tone === 'good' || stat.tone === 'bad' ? stat.tone : undefined,
      }
    case 'recovery':
      if (stat.sleep_seconds === null) return null
      return {
        label: t('app.rail.sleep'),
        value: duration(stat.sleep_seconds, t),
        note: stat.readiness === null ? undefined : String(stat.readiness),
        tone: stat.tone === 'good' || stat.tone === 'bad' ? stat.tone : undefined,
      }
    case 'nutrition':
      if (stat.calories === null) return null
      return { label: t('app.rail.nutrition'), value: t('app.unit.kcal_value', { value: formatNumber(stat.calories, lang, 0) }) }
    case 'workouts':
      if (stat.days_since === null) return null
      return { label: t('app.rail.workout'), value: t('app.rail.days_ago', { n: stat.days_since }) }
  }
}

/** The desktop rail: the log button, today, the rubrics with their sections, a status card, and
 *  the account rows. The amber plate slides to the active section. */
export function Rail({ active }: { active: ScreenId }) {
  const { t, lang } = useT()
  const session = useSession()
  const rubrics = rubricsOf(session.nav.items)
  const nav = useRef<HTMLElement>(null)
  const current = navScreen(active)

  useLayoutEffect(() => {
    const el = nav.current
    if (el === null) return
    const place = () => {
      const on = el.querySelector<HTMLElement>('.rail-a.on')
      const ink = el.querySelector<HTMLElement>('.rail-ink')
      if (ink === null) return
      if (on === null) {
        ink.style.opacity = '0'
        return
      }
      ink.style.opacity = '1'
      ink.style.height = `${on.offsetHeight}px`
      ink.style.transform = `translateY(${on.offsetTop}px)`
    }
    place()
    const observer = new ResizeObserver(place)
    observer.observe(el)
    return () => observer.disconnect()
  }, [current, rubrics.length])

  const rows = session.rail.map((s) => statRow(s, t, lang)).filter((r) => r !== null)

  return (
    <aside className="rail">
      <div className="brand">Vitals</div>
      <button type="button" className="rail-log" onClick={() => toggleLogSheet('weight')}>
        <Icon name="plus" />
        {t('app.log')}
        <kbd>N</kbd>
      </button>
      <nav ref={nav} className="rail-nav">
        <span className="rail-ink" />
        <ScreenLink screen="today" mode="tab" className={cx('rail-a', 'pinned', current === 'today' && 'on')}>
          <span className="ic">
            <Icon name="today" />
          </span>
          <span>{t('nav.today')}</span>
        </ScreenLink>
        {rubrics.map((rubric) => (
          <div key={rubric.id}>
            <div className="rail-g">{t(`masthead.rubric.${rubric.id}`)}</div>
            {rubric.sections.map((s) => (
              <ScreenLink key={s.key} screen={s.screen} mode="tab" className={cx('rail-a', !BUILT_SCREENS.has(s.screen) && 'soon', current === s.screen && 'on')}>
                <span className="ic">
                  <Icon name={s.icon} />
                </span>
                <span>{t(SCREEN_TITLE_KEY[s.screen])}</span>
              </ScreenLink>
            ))}
          </div>
        ))}
      </nav>
      <div className="rail-status">
        {rows.map((row) => (
          <div key={row.label} className="rs">
            <span>{row.label}</span>
            <b>
              {row.value}
              {row.note !== undefined && <small className={row.tone}>{row.note}</small>}
            </b>
          </div>
        ))}
      </div>
      <div className="rail-foot">
        <ScreenLink screen="share" mode="tab" className={cx(current === 'share' && 'on')}>
          <Icon name="clipboard" />
          {t('app.nav.share')}
        </ScreenLink>
        <ScreenLink screen="settings" mode="tab" className={cx(current === 'settings' && 'on')}>
          <Icon name="sliders" />
          {t('nav.settings')}
        </ScreenLink>
      </div>
    </aside>
  )
}
