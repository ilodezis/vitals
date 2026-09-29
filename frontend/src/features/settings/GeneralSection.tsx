import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { api } from '@/api/client'
import { PrimaryButton } from '@/components/controls/PrimaryButton'
import { Section } from '@/components/controls/Section'
import { toast } from '@/components/controls/toast'
import { useT } from '@/i18n/useT'
import type { SettingsView } from './useSettingsView'

interface GeneralSectionProps {
  settings: SettingsView
}

const CORE_MODULES = new Set([
  'today',
  'more',
  'weight',
  'measures',
  'recovery',
  'sleep',
  'nights',
  'activities',
  'labs',
  'reports',
  'charts',
  'share',
  'settings',
])

const MODULE_GROUPS = [
  {
    nameKey: 'masthead.rubric.health',
    defaultName: 'Здоровье',
    items: [
      { id: 'weight', label: 'Вес', core: true },
      { id: 'recovery', label: 'Восстановление', core: true },
      { id: 'workouts', label: 'Тренировки', core: false },
      { id: 'nutrition', label: 'Питание', core: false },
      { id: 'glp1', label: 'GLP-1', core: false },
      { id: 'hrt', label: 'ГЗТ', core: false },
    ],
  },
  {
    nameKey: 'masthead.rubric.markers',
    defaultName: 'Маркеры',
    items: [
      { id: 'labs', label: 'Анализы', core: true },
      { id: 'genetics', label: 'Генетика', core: false },
    ],
  },
  {
    nameKey: 'masthead.rubric.lifestyle',
    defaultName: 'Образ жизни',
    items: [
      { id: 'supplements', label: 'Добавки', core: false },
      { id: 'skincare', label: 'Уход за кожей', core: false },
    ],
  },
  {
    nameKey: 'masthead.rubric.journal',
    defaultName: 'Журнал',
    items: [
      { id: 'interactions', label: 'Взаимодействия', core: false },
      { id: 'signals', label: 'Симптомы', core: false },
      { id: 'timeline', label: 'Хроника', core: false },
      { id: 'reports', label: 'Отчёты', core: true },
      { id: 'charts', label: 'Графики', core: true },
    ],
  },
  {
    nameKey: 'nav.weight',
    defaultName: 'Вес',
    items: [{ id: 'body_comp', label: 'Состав тела', core: false }],
  },
]

export function GeneralSection({ settings }: GeneralSectionProps) {
  const { t } = useT()
  const queryClient = useQueryClient()

  // Profile form state
  const [heightCm, setHeightCm] = useState(settings.profile.height_cm)
  const [userAge, setUserAge] = useState(settings.profile.user_age)
  const [sex, setSex] = useState(settings.profile.sex)
  const [timezone, setTimezone] = useState(settings.profile.timezone)
  const [userProgram, setUserProgram] = useState(settings.profile.user_program)
  const [userGoals, setUserGoals] = useState(settings.profile.user_goals)

  // Nutrition form state
  const [proteinTarget, setProteinTarget] = useState(settings.nutrition_goals.nutrition_protein_target_g)
  const [calMin, setCalMin] = useState(settings.nutrition_goals.nutrition_calories_min)
  const [calMax, setCalMax] = useState(settings.nutrition_goals.nutrition_calories_max)

  // Language state
  const [lang, setLang] = useState(settings.language.language)

  // Profile save
  const handleSaveProfile = async () => {
    try {
      const res = await api.POST('/api/v1/settings/profile', {
        body: {
          height_cm: heightCm,
          user_age: userAge,
          sex,
          timezone,
          user_program: userProgram,
          user_goals: userGoals,
        },
      })
      if (res.data) {
        toast(t('settings.saved.profile'))
        void queryClient.invalidateQueries({ queryKey: ['settings'] })
        return true
      }
      return false
    } catch (err: any) {
      toast(err.message || 'Error saving profile', { icon: 'warn' })
      return false
    }
  }

  // Nutrition save
  const handleSaveNutrition = async () => {
    try {
      const res = await api.POST('/api/v1/settings/nutrition', {
        body: {
          nutrition_protein_target_g: proteinTarget,
          nutrition_calories_min: calMin,
          nutrition_calories_max: calMax,
        },
      })
      if (res.data) {
        toast(t('settings.saved.nutrition'))
        void queryClient.invalidateQueries({ queryKey: ['settings'] })
        return true
      }
      return false
    } catch (err: any) {
      toast(err.message || 'Error saving nutrition goals', { icon: 'warn' })
      return false
    }
  }

  // Language save
  const handleSaveLanguage = async () => {
    try {
      const res = await api.POST('/api/v1/settings/language', {
        body: { language: lang },
      })
      if (res.data) {
        toast(t('settings.saved.language'))
        void queryClient.invalidateQueries({ queryKey: ['settings'] })
        void queryClient.invalidateQueries({ queryKey: ['session'] })
        window.location.reload()
        return true
      }
      return false
    } catch (err: any) {
      toast(err.message || 'Error saving language', { icon: 'warn' })
      return false
    }
  }

  // Module toggle
  const handleToggleModule = async (moduleId: string, currentEnabled: boolean) => {
    if (CORE_MODULES.has(moduleId)) return
    try {
      const res = await api.POST('/api/v1/settings/modules', {
        body: { module: moduleId, enabled: !currentEnabled },
      })
      if (res.data) {
        toast(t('settings.saved.modules'))
        void queryClient.invalidateQueries({ queryKey: ['settings'] })
        void queryClient.invalidateQueries({ queryKey: ['session'] })
      }
    } catch (err: any) {
      toast(err.message || 'Error updating module', { icon: 'warn' })
    }
  }

  return (
    <div className="grid">
      <div className="c5">
        {/* Language */}
        <Section title={t('settings.language_title')} className="set-sec">
          <p className="sub set-d">{t('settings.language_description')}</p>
          <div className="form">
            <div className="seg mb-3">
              <button
                type="button"
                className={lang === 'ru' ? 'on' : ''}
                onClick={() => setLang('ru')}
              >
                Русский
              </button>
              <button
                type="button"
                className={lang === 'en' ? 'on' : ''}
                onClick={() => setLang('en')}
              >
                English
              </button>
            </div>
            <div className="set-save">
              <PrimaryButton onPress={handleSaveLanguage}>
                {t('settings.language_save')}
              </PrimaryButton>
            </div>
          </div>
        </Section>

        {/* Modules */}
        <Section title={t('modules.title')} className="set-sec">
          <p className="sub set-d">{t('modules.description')}</p>
          <div className="form">
            {MODULE_GROUPS.map((group, idx) => (
              <div key={idx} className="mod-g">
                <span className="flabel">{t(group.nameKey)}</span>
                <div className="opts" style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                  {group.items.map((it) => {
                    const isCore = it.core || CORE_MODULES.has(it.id)
                    const isEnabled = isCore || (settings.modules.enabled_modules ?? {})[it.id] !== false
                    return (
                      <button
                        key={it.id}
                        type="button"
                        className={`opt ${isEnabled ? 'on' : ''} ${isCore ? 'lock' : ''}`}
                        title={isCore ? 'Базовый модуль — отключение недоступно' : undefined}
                        onClick={() => !isCore && handleToggleModule(it.id, isEnabled)}
                        disabled={isCore}
                      >
                        {it.label}
                        {isCore && <span className="hint" style={{ marginLeft: '4px', opacity: 0.6, fontSize: '10px' }}>базовый</span>}
                      </button>
                    )
                  })}
                </div>
              </div>
            ))}
          </div>
        </Section>
      </div>

      <div className="c7">
        {/* Profile */}
        <Section title={t('settings.profile_title')} className="set-sec">
          <p className="sub set-d">{t('settings.profile_description')}</p>
          <div className="form space-y-3">
            <div className="grid grid-cols-3 gap-2">
              <label className="field">
                <span className="flabel">{t('settings.height')}</span>
                <input
                  type="text"
                  inputMode="numeric"
                  className="input"
                  value={heightCm}
                  onChange={(e) => setHeightCm(e.target.value)}
                />
              </label>
              <label className="field">
                <span className="flabel">{t('settings.age')}</span>
                <input
                  type="text"
                  inputMode="numeric"
                  className="input"
                  value={userAge}
                  onChange={(e) => setUserAge(e.target.value)}
                />
              </label>
              <label className="field">
                <span className="flabel">{t('settings.sex')}</span>
                <select
                  className="input"
                  value={sex}
                  onChange={(e) => setSex(e.target.value)}
                >
                  <option value="male">{t('settings.sex_male')}</option>
                  <option value="female">{t('settings.sex_female')}</option>
                </select>
              </label>
            </div>

            <label className="field">
              <span className="flabel">{t('settings.timezone')}</span>
              <select
                className="input"
                value={timezone}
                onChange={(e) => setTimezone(e.target.value)}
              >
                <option value="Europe/Chisinau">Europe/Chisinau</option>
                <option value="Europe/Moscow">Europe/Moscow</option>
                <option value="Europe/Berlin">Europe/Berlin</option>
                <option value="UTC">UTC</option>
              </select>
              <p className="fhint">{t('settings.timezone_hint')}</p>
            </label>

            <label className="field">
              <span className="flabel">{t('settings.program')}</span>
              <input
                className="input"
                placeholder={t('settings.program_placeholder')}
                value={userProgram}
                onChange={(e) => setUserProgram(e.target.value)}
              />
              <p className="fhint">{t('settings.program_hint')}</p>
            </label>

            <label className="field">
              <span className="flabel">{t('settings.goals_label')}</span>
              <input
                className="input"
                placeholder={t('settings.goals_placeholder')}
                value={userGoals}
                onChange={(e) => setUserGoals(e.target.value)}
              />
              <p className="fhint">{t('settings.goals_hint')}</p>
            </label>

            <div className="set-save">
              <PrimaryButton onPress={handleSaveProfile}>
                {t('settings.save_profile')}
              </PrimaryButton>
            </div>
          </div>
        </Section>

        {/* Nutrition Goals */}
        <Section title={t('settings.nutrition_title')} className="set-sec">
          <p className="sub set-d">{t('settings.nutrition_hint')}</p>
          <div className="form space-y-3">
            <div className="grid grid-cols-3 gap-2">
              <label className="field">
                <span className="flabel">{t('settings.protein_target')}</span>
                <input
                  type="text"
                  inputMode="numeric"
                  className="input"
                  value={proteinTarget}
                  onChange={(e) => setProteinTarget(e.target.value)}
                />
              </label>
              <label className="field">
                <span className="flabel">{t('settings.cal_min')}</span>
                <input
                  type="text"
                  inputMode="numeric"
                  className="input"
                  value={calMin}
                  onChange={(e) => setCalMin(e.target.value)}
                />
              </label>
              <label className="field">
                <span className="flabel">{t('settings.cal_max')}</span>
                <input
                  type="text"
                  inputMode="numeric"
                  className="input"
                  value={calMax}
                  onChange={(e) => setCalMax(e.target.value)}
                />
              </label>
            </div>

            <div className="set-save">
              <PrimaryButton onPress={handleSaveNutrition}>
                {t('settings.save_nutrition')}
              </PrimaryButton>
            </div>
          </div>
        </Section>
      </div>
    </div>
  )
}
