import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { api } from '@/api/client'
import { PrimaryButton } from '@/components/controls/PrimaryButton'
import { Section } from '@/components/controls/Section'
import { toast } from '@/components/controls/toast'
import { Icon } from '@/components/icons/Icon'
import { useT } from '@/i18n/useT'
import type { SettingsView } from './useSettingsView'

interface ProactiveSectionProps {
  settings: SettingsView
}

const WEEKDAYS = [
  { id: 'mon', label: 'Пн' },
  { id: 'tue', label: 'Вт' },
  { id: 'wed', label: 'Ср' },
  { id: 'thu', label: 'Чт' },
  { id: 'fri', label: 'Пт' },
  { id: 'sat', label: 'Сб' },
  { id: 'sun', label: 'Вс' },
]

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
    try {
      const nudgesList: string[] = []
      if (nudgeActivity) nudgesList.push('activity')
      if (nudgeNutrition) nudgesList.push('nutrition')
      if (nudgeData) nudgesList.push('data')

      const res = await api.POST('/api/v1/settings/proactive', {
        body: {
          brief_time: briefTime,
          evening_time: eveningTime,
          quiet_start: quietStart,
          quiet_end: quietEnd,
          daily_budget: parseInt(dailyBudget, 10) || 4,
          garmin_sync_hours: parseInt(syncHours, 10) || 4,
          garmin_weight_export_minutes: parseInt(weightExportMinutes, 10) || 30,
          garmin_weight_max_age_days: parseInt(weightMaxAgeDays, 10) || 2,
          pulse_seconds: parseInt(pulseSeconds, 10) || 900,
          pulse_start_hour: parseInt(pulseStartHour, 10) || 8,
          pulse_end_hour: parseInt(pulseEndHour, 10) || 22,
          nudges: nudgesList,
          week_template: weekTemplate as any,
        },
      })
      if (res.data) {
        toast(t('settings.saved.proactive'))
        void queryClient.invalidateQueries({ queryKey: ['settings'] })
        return true
      }
      return false
    } catch (err: any) {
      toast(err.message || 'Error saving proactive settings', { icon: 'warn' })
      return false
    }
  }

  const breaker = settings.garmin.breaker as { used?: number; max?: number; paused?: boolean } | null

  return (
    <Section title={t('settings.proactive_title')} className="set-sec narrow">
      <p className="sub set-d">{t('settings.proactive_description')}</p>

      <div className="form space-y-4">
        {/* Times */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
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
        <label className="field">
          <span className="flabel">{t('settings.daily_budget')}</span>
          <input
            type="text"
            inputMode="numeric"
            className="input w-24"
            value={dailyBudget}
            onChange={(e) => setDailyBudget(e.target.value)}
          />
          <p className="fhint">{t('settings.budget_hint')}</p>
        </label>

        {/* Nudges */}
        <div>
          <span className="flabel block mb-2">{t('settings.nudges_label')}</span>
          <div className="opts" style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            <button
              type="button"
              className={`opt text-left ${nudgeActivity ? 'on' : ''}`}
              onClick={() => setNudgeActivity(!nudgeActivity)}
            >
              {t('settings.nudge.activity')}
            </button>
            <button
              type="button"
              className={`opt text-left ${nudgeNutrition ? 'on' : ''}`}
              onClick={() => setNudgeNutrition(!nudgeNutrition)}
            >
              {t('settings.nudge.nutrition')}
            </button>
            <button
              type="button"
              className={`opt text-left ${nudgeData ? 'on' : ''}`}
              onClick={() => setNudgeData(!nudgeData)}
            >
              {t('settings.nudge.data')}
            </button>
          </div>
          <p className="fhint mt-1">{t('settings.nudges_hint')}</p>
        </div>

        {/* Week template */}
        <div>
          <span className="flabel block mb-2">{t('settings.week_template_label')}</span>
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
                  <span className="m font-medium">{d.label}</span>
                  <select
                    className="input"
                    value={current.where}
                    onChange={(e) => handleDayChange(d.id, 'where', e.target.value)}
                  >
                    <option value="office">В офисе</option>
                    <option value="remote">Дома</option>
                    <option value="off">Выходной</option>
                  </select>
                  <select
                    className="input"
                    value={current.gym ? 'true' : 'false'}
                    onChange={(e) => handleDayChange(d.id, 'gym', e.target.value === 'true')}
                  >
                    <option value="true">Зал</option>
                    <option value="false">Отдых</option>
                  </select>
                  <select
                    className="input"
                    value={current.load || 'normal'}
                    onChange={(e) => handleDayChange(d.id, 'load', e.target.value)}
                  >
                    <option value="normal">Обычная</option>
                    <option value="light">Лёгкая</option>
                    <option value="heavy">Тяжёлая</option>
                  </select>
                </div>
              )
            })}
          </div>
          <p className="fhint mt-2">{t('settings.week_template_hint')}</p>
        </div>

        {/* Garmin schedule */}
        <div className="pt-4 border-t border-[var(--line)]">
          <span className="flabel font-semibold block mb-2">{t('settings.garmin_schedule_label')}</span>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-2">
            <label className="field">
              <span className="flabel">{t('settings.sync_hours')}</span>
              <input
                type="text"
                inputMode="numeric"
                className="input"
                value={syncHours}
                onChange={(e) => setSyncHours(e.target.value)}
              />
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
            </label>
            <label className="field">
              <span className="flabel">{t('settings.pulse_start_hour')}</span>
              <input
                type="text"
                inputMode="numeric"
                className="input"
                value={pulseStartHour}
                onChange={(e) => setPulseStartHour(e.target.value)}
              />
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
            </label>
          </div>
          <p className="fhint mt-2">{t('settings.garmin_schedule_hint')}</p>
        </div>

        {/* Breaker Alert */}
        <div className="alert flex items-start gap-2">
          <Icon name="info" />
          <div>
            {breaker
              ? breaker.paused
                ? t('settings.breaker_paused', { used: breaker.used ?? 0, max: breaker.max ?? 5 })
                : t('settings.breaker_ok', { used: breaker.used ?? 1, max: breaker.max ?? 5 })
              : t('settings.breaker_ok', { used: 1, max: 5 })}
          </div>
        </div>

        <div className="set-save">
          <PrimaryButton onPress={handleSave}>
            {t('settings.save_proactive')}
          </PrimaryButton>
        </div>
      </div>
    </Section>
  )
}
