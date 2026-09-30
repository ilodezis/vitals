import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { api, failText, ok } from '@/api/client'
import { Section } from '@/components/controls/Section'
import { toast } from '@/components/controls/toast'
import { useT } from '@/i18n/useT'
import { buildProactiveNumbers, type ProactiveNumberKey } from './proactiveBody'
import type { SettingsView } from './useSettingsView'

interface ProactiveSectionProps {
  settings: SettingsView
}

const WEEKDAYS = [
  { id: 'mon' },
  { id: 'tue' },
  { id: 'wed' },
  { id: 'thu' },
  { id: 'fri' },
  { id: 'sat' },
  { id: 'sun' },
]

const NUMBER_LABELS: Record<ProactiveNumberKey, string> = {
  dailyBudget: 'settings.daily_budget',
  syncHours: 'settings.sync_hours',
  weightExportMinutes: 'settings.weight_export_minutes',
  weightMaxAgeDays: 'settings.weight_max_age_days',
  pulseSeconds: 'settings.pulse_seconds',
  pulseStartHour: 'settings.pulse_start_hour',
  pulseEndHour: 'settings.pulse_end_hour',
}

export function ProactiveSection({ settings }: ProactiveSectionProps) {
  const { t } = useT()
  const queryClient = useQueryClient()

  // Times and budget
  const [briefTime, setBriefTime] = useState(settings.proactive.brief_time)
  const [eveningTime, setEveningTime] = useState(settings.proactive.evening_time)
  const [quietStart, setQuietStart] = useState(settings.proactive.quiet_start)
  const [quietEnd, setQuietEnd] = useState(settings.proactive.quiet_end)
  const [dailyBudget, setDailyBudget] = useState(String(settings.proactive.daily_budget))

  // Nudges
  const [nudgeActivity, setNudgeActivity] = useState(Boolean(settings.proactive.nudges?.a ?? settings.proactive.nudges?.activity))
  const [nudgeNutrition, setNudgeNutrition] = useState(Boolean(settings.proactive.nudges?.n ?? settings.proactive.nudges?.nutrition ?? true))
  const [nudgeData, setNudgeData] = useState(Boolean(settings.proactive.nudges?.d ?? settings.proactive.nudges?.data ?? true))

  // Week template
  interface DaySchedule {
    where: string
    gym: boolean
    load: string
  }

  const [weekTemplate, setWeekTemplate] = useState<Record<string, DaySchedule>>(() => {
    const raw = (settings.proactive.week_template ?? {}) as Record<string, Record<string, any>>
    const out: Record<string, DaySchedule> = {}
    for (const d of WEEKDAYS) {
      const existing = raw[d.id] ?? {}
      out[d.id] = {
        where: typeof existing.where === 'string' ? existing.where : (d.id === 'sat' || d.id === 'sun' ? 'off' : 'office'),
        gym: typeof existing.gym === 'boolean' ? existing.gym : ['mon', 'wed', 'fri'].includes(d.id),
        load: typeof existing.load === 'string' ? existing.load : (['mon', 'wed', 'fri'].includes(d.id) ? 'normal' : 'light'),
      }
    }
    return out
  })

  // Garmin polling
  const [syncHours, setSyncHours] = useState(String(settings.proactive.garmin_sync_hours))
  const [weightExportMinutes, setWeightExportMinutes] = useState(String(settings.proactive.garmin_weight_export_minutes))
  const [weightMaxAgeDays, setWeightMaxAgeDays] = useState(String(settings.proactive.garmin_weight_max_age_days))
  const [pulseSeconds, setPulseSeconds] = useState(String(settings.proactive.pulse_seconds))
  const [pulseStartHour, setPulseStartHour] = useState(String(settings.proactive.pulse_start_hour))
  const [pulseEndHour, setPulseEndHour] = useState(String(settings.proactive.pulse_end_hour))

  const handleDayChange = (dayId: string, field: 'where' | 'gym' | 'load', value: string | boolean) => {
    setWeekTemplate((prev) => {
      const current = prev[dayId] ?? { where: 'office', gym: false, load: 'normal' }
      return {
        ...prev,
        [dayId]: {
          ...current,
          [field]: value,
        },
      }
    })
  }

  const handleSave = async () => {
    const read = buildProactiveNumbers({
      dailyBudget,
      syncHours,
      weightExportMinutes,
      weightMaxAgeDays,
      pulseSeconds,
      pulseStartHour,
      pulseEndHour,
    })
    if (!read.ok) {
      const fields = read.invalid.map((key) => t(NUMBER_LABELS[key])).join(', ')
      toast(t('settings.proactive_invalid', { fields }), { icon: 'warn' })
      return false
    }
    try {
      const nudgesList: string[] = []
      if (nudgeActivity) nudgesList.push('activity')
      if (nudgeNutrition) nudgesList.push('nutrition')
      if (nudgeData) nudgesList.push('data')

      await ok(api.POST('/api/v1/settings/proactive', {
        body: {
          brief_time: briefTime,
          evening_time: eveningTime,
          quiet_start: quietStart,
          quiet_end: quietEnd,
          ...read.numbers,
          nudges: nudgesList,
          week_template: weekTemplate as any,
        },
      }))
      toast(t('settings.saved.proactive'))
      void queryClient.invalidateQueries({ queryKey: ['settings'] })
      return true
    } catch (err) {
      toast(failText(err, t('app.save_failed')), { icon: 'warn' })
      return false
    }
  }

  const breaker = settings.garmin.breaker as { used?: number; max?: number; paused?: boolean } | null

  return (
    <Section title={t('settings.proactive_title')} className="set-sec narrow">
      <p className="sub set-d">{t('settings.proactive_description')}</p>

      <div className="form">
        {/* Times */}
        <div className="set-grid-4">
          <label className="field">
            <span className="flabel">{t('settings.brief_time')}</span>
            <input
              type="time"
              className="input"
              value={briefTime}
              onChange={(e) => setBriefTime(e.target.value)}
            />
            <p className="fhint">{t('settings.brief_time_hint')}</p>
          </label>
          <label className="field">
            <span className="flabel">{t('settings.evening_time')}</span>
            <input
              type="time"
              className="input"
              value={eveningTime}
              onChange={(e) => setEveningTime(e.target.value)}
            />
            <p className="fhint">{t('settings.evening_time_hint')}</p>
          </label>
          <label className="field">
            <span className="flabel">{t('settings.quiet_start')}</span>
            <input
              type="time"
              className="input"
              value={quietStart}
              onChange={(e) => setQuietStart(e.target.value)}
            />
          </label>
          <label className="field">
            <span className="flabel">{t('settings.quiet_end')}</span>
            <input
              type="time"
              className="input"
              value={quietEnd}
              onChange={(e) => setQuietEnd(e.target.value)}
            />
          </label>
        </div>

        {/* Daily budget */}
        <label className="field set-narrow-field">
          <span className="flabel">{t('settings.daily_budget')}</span>
          <input
            type="text"
            inputMode="numeric"
            className="input"
            value={dailyBudget}
            onChange={(e) => setDailyBudget(e.target.value)}
          />
          <p className="fhint">{t('settings.budget_hint')}</p>
        </label>

        {/* Nudges */}
        <div>
          <span className="flabel block">
            {t('settings.nudges_label')}
          </span>
          <div className="opts opts-col">
            <button
              type="button"
              className={`opt ${nudgeActivity ? 'on' : ''}`}
              onClick={() => setNudgeActivity(!nudgeActivity)}
            >
              {t('settings.nudge.activity')}
            </button>
            <button
              type="button"
              className={`opt ${nudgeNutrition ? 'on' : ''}`}
              onClick={() => setNudgeNutrition(!nudgeNutrition)}
            >
              {t('settings.nudge.nutrition')}
            </button>
            <button
              type="button"
              className={`opt ${nudgeData ? 'on' : ''}`}
              onClick={() => setNudgeData(!nudgeData)}
            >
              {t('settings.nudge.data')}
            </button>
          </div>
          <p className="fhint set-mt1">{t('settings.nudges_hint')}</p>
        </div>

        {/* Week template */}
        <div>
          <span className="flabel block">
            {t('settings.week_template_label')}
          </span>
          <div className="wk">
            <div className="wk-r wk-h">
              <span></span>
              <span>{t('settings.question.where')}</span>
              <span>{t('settings.question.gym')}</span>
              <span>{t('settings.question.load')}</span>
            </div>
            {WEEKDAYS.map((d) => {
              const current = weekTemplate[d.id] || { where: 'office', gym: false, load: 'normal' }
              return (
                <div key={d.id} className="wk-r">
                  <span className="m wk-day">
                    {t(`proactive.day.${d.id}`)}
                  </span>
                  <select
                    className="input"
                    value={current.where}
                    onChange={(e) => handleDayChange(d.id, 'where', e.target.value)}
                  >
                    <option value="office">{t('settings.where.office')}</option>
                    <option value="remote">{t('settings.where.remote')}</option>
                    <option value="off">{t('settings.where.off')}</option>
                  </select>
                  <select
                    className="input"
                    value={current.gym ? 'true' : 'false'}
                    onChange={(e) => handleDayChange(d.id, 'gym', e.target.value === 'true')}
                  >
                    <option value="true">{t('settings.gym.yes')}</option>
                    <option value="false">{t('settings.gym.no')}</option>
                  </select>
                  <select
                    className="input"
                    value={current.load || 'normal'}
                    onChange={(e) => handleDayChange(d.id, 'load', e.target.value)}
                  >
                    <option value="normal">{t('settings.load.normal')}</option>
                    <option value="light">{t('settings.load.light')}</option>
                    <option value="heavy">{t('settings.load.heavy')}</option>
                  </select>
                </div>
              )
            })}
          </div>
          <p className="fhint set-mt2">{t('settings.week_template_hint')}</p>
        </div>

        {/* Garmin schedule */}
        <div className="set-sub-sec">
          <span className="flabel block strong">
            {t('settings.garmin_schedule_label')}
          </span>
          <p className="fhint set-mb3">
            {t('settings.garmin_schedule_hint')}
          </p>

          <div className="set-grid-4">
            <label className="field">
              <span className="flabel">{t('settings.sync_hours')}</span>
              <input
                type="text"
                inputMode="numeric"
                className="input"
                value={syncHours}
                onChange={(e) => setSyncHours(e.target.value)}
              />
              <p className="fhint">{t('settings.sync_hours_hint')}</p>
            </label>
            <label className="field">
              <span className="flabel">{t('settings.weight_export_minutes')}</span>
              <input
                type="text"
                inputMode="numeric"
                className="input"
                value={weightExportMinutes}
                onChange={(e) => setWeightExportMinutes(e.target.value)}
              />
              <p className="fhint">{t('settings.weight_export_minutes_hint')}</p>
            </label>
            <label className="field">
              <span className="flabel">{t('settings.weight_max_age_days')}</span>
              <input
                type="text"
                inputMode="numeric"
                className="input"
                value={weightMaxAgeDays}
                onChange={(e) => setWeightMaxAgeDays(e.target.value)}
              />
              <p className="fhint">{t('settings.weight_max_age_days_hint')}</p>
            </label>
            <label className="field">
              <span className="flabel">{t('settings.pulse_seconds')}</span>
              <input
                type="text"
                inputMode="numeric"
                className="input"
                value={pulseSeconds}
                onChange={(e) => setPulseSeconds(e.target.value)}
              />
              <p className="fhint">{t('settings.pulse_seconds_hint')}</p>
            </label>
          </div>

          <div className="set-grid-2 set-mt3">
            <label className="field">
              <span className="flabel">{t('settings.pulse_start_hour')}</span>
              <input
                type="text"
                inputMode="numeric"
                className="input"
                value={pulseStartHour}
                onChange={(e) => setPulseStartHour(e.target.value)}
              />
              <p className="fhint">{t('settings.pulse_start_hour_hint')}</p>
            </label>
            <label className="field">
              <span className="flabel">{t('settings.pulse_end_hour')}</span>
              <input
                type="text"
                inputMode="numeric"
                className="input"
                value={pulseEndHour}
                onChange={(e) => setPulseEndHour(e.target.value)}
              />
              <p className="fhint">{t('settings.pulse_end_hour_hint')}</p>
            </label>
          </div>

          {breaker && (
            <div className="alert info set-mt3">
              <div>
                <b>{t('settings.garmin_breaker')}</b>
                <p className="set-note">
                  {breaker.paused
                    ? t('settings.breaker_paused')
                    : breaker.used !== undefined
                      ? t('settings.breaker_status', { used: breaker.used, max: breaker.max ?? 10 })
                      : t('settings.breaker_unknown')}
                </p>
              </div>
            </div>
          )}
        </div>

        <div className="set-save">
          <button type="button" className="ghost" onClick={handleSave}>
            {t('settings.save_proactive')}
          </button>
        </div>
      </div>
    </Section>
  )
}
