import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { api, failText, ok } from '@/api/client'
import type { components } from '@/api/schema'
import { Section } from '@/components/controls/Section'
import { toast } from '@/components/controls/toast'
import { EnvironmentAlerts } from '@/features/environment/EnvironmentSettings'
import { useT } from '@/i18n/useT'
import { cx } from '@/lib/cx'
import { moduleOn, SaveRow } from './parts'
import { readProactiveNumbers } from './proactiveBody'
import type { SettingsView } from './useSettingsView'

interface NotificationsSectionProps {
  settings: SettingsView
}

const WEEKDAYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'] as const

// A type, not an interface: it has to pass as the API's loose `{ [key: string]: unknown }`.
type DaySchedule = {
  where: string
  gym: boolean
  load: string
}

const NUDGES = ['activity', 'nutrition', 'data', 'environment', 'skincare'] as const
type Nudge = (typeof NUDGES)[number]

/** The nudges as saved. Older rows keep them under one-letter keys; a nudge never set reads as
 *  its default (everything but activity is on). */
export function nudgesOf(saved: Record<string, boolean> | null | undefined): Record<Nudge, boolean> {
  const raw = saved ?? {}
  return {
    activity: Boolean(raw.a ?? raw.activity),
    nutrition: Boolean(raw.n ?? raw.nutrition ?? true),
    data: Boolean(raw.d ?? raw.data ?? true),
    environment: Boolean(raw.e ?? raw.environment ?? true),
    skincare: Boolean(raw.skincare ?? true),
  }
}

/** When the bot may speak first and what about: its schedule, the nudges, the station's alerts
 *  and the week it assumes until told otherwise. */
export function NotificationsSection({ settings }: NotificationsSectionProps) {
  const envOn = moduleOn(settings, 'environment')
  return (
    <>
      <BotSchedule settings={settings} />
      <Nudges settings={settings} />
      {envOn && <EnvironmentAlerts />}
      <WeekTemplate settings={settings} />
    </>
  )
}

function useProactiveSave() {
  const { t } = useT()
  const queryClient = useQueryClient()
  return async (body: components['schemas']['ProactiveUpdate'], savedKey?: string) => {
    try {
      await ok(api.POST('/api/v1/settings/proactive', { body }))
      if (savedKey !== undefined) toast(t(savedKey))
      void queryClient.invalidateQueries({ queryKey: ['settings'] })
      return true
    } catch (err) {
      toast(failText(err, t('app.save_failed')), { icon: 'warn' })
      return false
    }
  }
}

function BotSchedule({ settings }: NotificationsSectionProps) {
  const { t } = useT()
  const save = useProactiveSave()
  const p = settings.proactive
  const [briefTime, setBriefTime] = useState(p.brief_time)
  const [eveningTime, setEveningTime] = useState(p.evening_time)
  const [skincareMorning, setSkincareMorning] = useState(p.skincare_morning_time)
  const [skincareEvening, setSkincareEvening] = useState(p.skincare_evening_time)
  const [dayEnd, setDayEnd] = useState(p.day_end)
  const skincareOn = moduleOn(settings, 'skincare')
  const [quietStart, setQuietStart] = useState(p.quiet_start)
  const [quietEnd, setQuietEnd] = useState(p.quiet_end)
  const [dailyBudget, setDailyBudget] = useState(String(p.daily_budget))

  const dirty =
    briefTime !== p.brief_time ||
    eveningTime !== p.evening_time ||
    skincareMorning !== p.skincare_morning_time ||
    skincareEvening !== p.skincare_evening_time ||
    dayEnd !== p.day_end ||
    quietStart !== p.quiet_start ||
    quietEnd !== p.quiet_end ||
    dailyBudget !== String(p.daily_budget)

  const saveSchedule = async () => {
    const read = readProactiveNumbers({ dailyBudget })
    if (!read.ok) {
      toast(t('settings.proactive_invalid', { fields: t('settings.daily_budget') }), { icon: 'warn' })
      return false
    }
    return save(
      {
        brief_time: briefTime,
        evening_time: eveningTime,
        skincare_morning_time: skincareMorning,
        skincare_evening_time: skincareEvening,
        day_end: dayEnd,
        quiet_start: quietStart,
        quiet_end: quietEnd,
        ...read.numbers,
      },
      'settings.saved.proactive',
    )
  }

  const time = (label: string, value: string, set: (v: string) => void, hint?: string) => (
    <label className="field">
      <span className="flabel">{t(label)}</span>
      <input type="time" className="input" value={value} onChange={(e) => set(e.target.value)} />
      {hint !== undefined && <p className="fhint">{t(hint)}</p>}
    </label>
  )

  return (
    <Section title={t('settings.notify_schedule_title')} className="set-sec">
      <p className="sub set-d">{t('settings.notify_description')}</p>
      <div className="form">
        <div className="set-times-grid">
          {time('settings.brief_time', briefTime, setBriefTime, 'settings.brief_time_hint')}
          {time('settings.evening_time', eveningTime, setEveningTime, 'settings.evening_time_hint')}
        </div>
        {skincareOn && (
          <>
            <div className="set-times-grid set-mt3">
              {time('settings.skincare_morning_time', skincareMorning, setSkincareMorning)}
              {time('settings.skincare_evening_time', skincareEvening, setSkincareEvening)}
            </div>
            <p className="fhint set-mt1">{t('settings.skincare_time_hint')}</p>
          </>
        )}
        <div className="set-times-grid set-mt3">
          {time('settings.quiet_start', quietStart, setQuietStart)}
          {time('settings.quiet_end', quietEnd, setQuietEnd)}
        </div>
        <div className="set-mt3 set-narrow-field">{time('settings.day_end', dayEnd, setDayEnd)}</div>
        <p className="fhint set-mt1">{t('settings.day_end_hint')}</p>
        <label className="field set-mt3 set-narrow-field">
          <span className="flabel">{t('settings.daily_budget')}</span>
          <input type="text" inputMode="numeric" className="input" value={dailyBudget} onChange={(e) => setDailyBudget(e.target.value)} />
        </label>
        <p className="fhint set-mt1">{t('settings.budget_hint')}</p>

        <SaveRow dirty={dirty} onSave={saveSchedule}>
          {t('settings.save_proactive')}
        </SaveRow>
      </div>
    </Section>
  )
}

/** Each nudge is a switch that applies on the tap, like the station's alerts below it. */
function Nudges({ settings }: NotificationsSectionProps) {
  const { t } = useT()
  const save = useProactiveSave()
  const [nudges, setNudges] = useState(() => nudgesOf(settings.proactive.nudges))
  // A nudge about a section that is off is kept as it is, just not offered.
  const shown = NUDGES.filter(
    (n) =>
      (n !== 'nutrition' || moduleOn(settings, 'nutrition')) &&
      (n !== 'environment' || moduleOn(settings, 'environment')) &&
      (n !== 'skincare' || moduleOn(settings, 'skincare')),
  )

  const flip = async (nudge: Nudge) => {
    const was = nudges
    const next = { ...nudges, [nudge]: !nudges[nudge] }
    setNudges(next)
    const saved = await save({ nudges: NUDGES.filter((n) => next[n]) })
    if (!saved) setNudges(was)
  }

  return (
    <Section title={t('settings.nudges_label')} className="set-sec">
      <p className="sub set-d">{t('settings.nudges_hint')}</p>
      <div className="set-switches">
        {shown.map((nudge) => (
          <button key={nudge} type="button" className={cx('tgl', nudges[nudge] && 'on')} aria-pressed={nudges[nudge]} onClick={() => void flip(nudge)}>
            <i />
            {t(`settings.nudge.${nudge}`)}
          </button>
        ))}
      </div>
    </Section>
  )
}

function weekOf(saved: Record<string, Record<string, unknown>> | null | undefined): Record<string, DaySchedule> {
  const raw = saved ?? {}
  const out: Record<string, DaySchedule> = {}
  for (const day of WEEKDAYS) {
    const existing = raw[day] ?? {}
    const weekend = day === 'sat' || day === 'sun'
    const gymDay = day === 'mon' || day === 'wed' || day === 'fri'
    out[day] = {
      where: typeof existing.where === 'string' ? existing.where : weekend ? 'off' : 'office',
      gym: typeof existing.gym === 'boolean' ? existing.gym : gymDay,
      load: typeof existing.load === 'string' ? existing.load : gymDay ? 'normal' : 'light',
    }
  }
  return out
}

function WeekTemplate({ settings }: NotificationsSectionProps) {
  const { t } = useT()
  const save = useProactiveSave()
  const savedWeek = weekOf(settings.proactive.week_template)
  const [week, setWeek] = useState(savedWeek)
  const dirty = JSON.stringify(week) !== JSON.stringify(savedWeek)

  const change = (day: string, field: keyof DaySchedule, value: string | boolean) => {
    setWeek((prev) => ({ ...prev, [day]: { ...(prev[day] as DaySchedule), [field]: value } }))
  }

  return (
    <Section title={t('settings.week_template_label')} className="set-sec">
      <p className="sub set-d">{t('settings.week_template_hint')}</p>
      <div className="form">
        <div className="wk">
          <div className="wk-r wk-h">
            <span></span>
            <span>{t('settings.question.where')}</span>
            <span>{t('settings.question.gym')}</span>
            <span>{t('settings.question.load')}</span>
          </div>
          {WEEKDAYS.map((day) => {
            const current = week[day] as DaySchedule
            return (
              <div key={day} className="wk-r">
                <span className="m wk-day">{t(`proactive.day.${day}`)}</span>
                <select className="input" aria-label={t('settings.question.where')} value={current.where} onChange={(e) => change(day, 'where', e.target.value)}>
                  <option value="office">{t('settings.where.office')}</option>
                  <option value="remote">{t('settings.where.remote')}</option>
                  <option value="off">{t('settings.where.off')}</option>
                </select>
                <select className="input" aria-label={t('settings.question.gym')} value={current.gym ? 'true' : 'false'} onChange={(e) => change(day, 'gym', e.target.value === 'true')}>
                  <option value="true">{t('settings.gym.yes')}</option>
                  <option value="false">{t('settings.gym.no')}</option>
                </select>
                <select className="input" aria-label={t('settings.question.load')} value={current.load} onChange={(e) => change(day, 'load', e.target.value)}>
                  <option value="normal">{t('settings.load.normal')}</option>
                  <option value="light">{t('settings.load.light')}</option>
                  <option value="heavy">{t('settings.load.heavy')}</option>
                </select>
              </div>
            )
          })}
        </div>
        <SaveRow dirty={dirty} onSave={() => save({ week_template: week }, 'settings.saved.week')}>
          {t('settings.save_week')}
        </SaveRow>
      </div>
    </Section>
  )
}
