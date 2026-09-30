import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { api, failText, ok } from '@/api/client'
import { useSession } from '@/app/session'
import { OptionGroup } from '@/components/controls/Choices'
import { PrimaryButton } from '@/components/controls/PrimaryButton'
import { Section } from '@/components/controls/Section'
import { toast } from '@/components/controls/toast'
import { useT } from '@/i18n/useT'
import type { NavItem } from '@/components/shell/nav'
import type { SettingsView } from './useSettingsView'

interface GeneralSectionProps {
  settings: SettingsView
}

export interface SettingsModuleItem {
  id: string
  titleKey: string
  core: boolean
  enabled: boolean
}

export interface SettingsModuleGroup {
  rubric: string
  rubricKey: string
  items: SettingsModuleItem[]
}

export const CORE_MODULES = new Set([
  'today',
  'more',
  'weight',
  'measures',
  'recovery',
  'garmin',
  'sleep',
  'nights',
  'activities',
  'labs',
  'reports',
  'charts',
  'share',
  'settings',
])

export function groupSettingsModules(
  navItems: NavItem[] = [],
  enabledModules: Record<string, boolean> = {},
): SettingsModuleGroup[] {
  const groupsByRubric = new Map<string, SettingsModuleItem[]>()

  for (const item of navItems) {
    const rubric = item.rubric || 'other'
    if (!groupsByRubric.has(rubric)) {
      groupsByRubric.set(rubric, [])
    }
    const id = item.key
    const isCore = CORE_MODULES.has(id)
    const isEnabled = isCore || enabledModules[id] !== false
    groupsByRubric.get(rubric)!.push({
      id,
      titleKey: `nav.${id}`,
      core: isCore,
      enabled: isEnabled,
    })
  }

  // body_comp is in 'health' group as a separate item
  const healthGroup = groupsByRubric.get('health')
  if (healthGroup) {
    const isCore = false
    const isEnabled = enabledModules['body_comp'] !== false
    if (!healthGroup.some((it) => it.id === 'body_comp')) {
      healthGroup.push({
        id: 'body_comp',
        titleKey: 'nav.body_comp',
        core: isCore,
        enabled: isEnabled,
      })
    }
  }

  return Array.from(groupsByRubric.entries()).map(([rubric, items]) => ({
    rubric,
    rubricKey: `masthead.rubric.${rubric}`,
    items,
  }))
}

export function GeneralSection({ settings }: GeneralSectionProps) {
  const { t } = useT()
  const session = useSession()
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

  // Dynamic modules grouped from session.nav.items
  const moduleGroups = groupSettingsModules(
    session?.nav?.items ?? [],
    settings.modules.enabled_modules ?? {},
  )

  // Profile save
  const handleSaveProfile = async () => {
    try {
      await ok(api.POST('/api/v1/settings/profile', {
        body: {
          height_cm: heightCm,
          user_age: userAge,
          sex,
          timezone,
          user_program: userProgram,
          user_goals: userGoals,
        },
      }))
      toast(t('settings.saved.profile'))
      void queryClient.invalidateQueries({ queryKey: ['settings'] })
      return true
    } catch (err) {
      toast(failText(err, t('app.save_failed')), { icon: 'warn' })
      return false
    }
  }

  // Nutrition save
  const handleSaveNutrition = async () => {
    try {
      await ok(api.POST('/api/v1/settings/nutrition', {
        body: {
          nutrition_protein_target_g: proteinTarget,
          nutrition_calories_min: calMin,
          nutrition_calories_max: calMax,
        },
      }))
      toast(t('settings.saved.nutrition'))
      void queryClient.invalidateQueries({ queryKey: ['settings'] })
      return true
    } catch (err) {
      toast(failText(err, t('app.save_failed')), { icon: 'warn' })
      return false
    }
  }

  // Language save
  const handleSaveLanguage = async () => {
    try {
      await ok(api.POST('/api/v1/settings/language', {
        body: { language: lang },
      }))
      toast(t('settings.saved.language'))
      void queryClient.invalidateQueries({ queryKey: ['settings'] })
      void queryClient.invalidateQueries({ queryKey: ['session'] })
      window.location.reload()
      return true
    } catch (err) {
      toast(failText(err, t('app.save_failed')), { icon: 'warn' })
      return false
    }
  }

  // Module toggle
  const handleToggleModule = async (moduleId: string, currentEnabled: boolean) => {
    if (CORE_MODULES.has(moduleId)) return
    try {
      await ok(api.POST('/api/v1/settings/modules', {
        body: { module: moduleId, enabled: !currentEnabled },
      }))
      toast(t('settings.saved.modules'))
      void queryClient.invalidateQueries({ queryKey: ['settings'] })
      void queryClient.invalidateQueries({ queryKey: ['session'] })
    } catch (err) {
      toast(failText(err, t('app.save_failed')), { icon: 'warn' })
    }
  }

  return (
    <div className="grid">
      <div className="c5">
        {/* Language */}
        <Section title={t('settings.language_title')} className="set-sec">
          <p className="sub set-d">{t('settings.language_description')}</p>
          <div className="form">
            <OptionGroup
              options={[
                { id: 'ru', label: t('settings.lang_ru') },
                { id: 'en', label: t('settings.lang_en') },
              ]}
              value={lang}
              onChange={(id) => setLang(id as 'ru' | 'en')}
            />
            <div className="set-save">
              <button type="button" className="ghost" onClick={handleSaveLanguage}>
                {t('settings.language_save')}
              </button>
            </div>
          </div>
        </Section>

        {/* Modules */}
        <Section title={t('modules.title')} className="set-sec">
          <p className="sub set-d">{t('modules.description')}</p>
          <div className="form">
            {moduleGroups.map((group, idx) => (
              <div key={idx} className="mod-g">
                <span className="flabel">{t(group.rubricKey)}</span>
                <div className="opts opts-wrap">
                  {group.items.map((it) => {
                    const isCore = it.core
                    const isEnabled = it.enabled
                    return (
                      <button
                        key={it.id}
                        type="button"
                        className={`opt ${isEnabled ? 'on' : ''} ${isCore ? 'lock' : ''}`}
                        title={isCore ? t('settings.module_core_title') : undefined}
                        onClick={() => !isCore && handleToggleModule(it.id, isEnabled)}
                        disabled={isCore}
                      >
                        {t(it.titleKey)}
                        {isCore && (
                          <span className="hint">
                            {t('settings.module_core_badge')}
                          </span>
                        )}
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
          <div className="form">
            <div className="set-fields-grid">
              <label className="field">
                <span className="flabel">{t('settings.field.height')}</span>
                <input
                  type="text"
                  inputMode="numeric"
                  className="input"
                  value={heightCm}
                  onChange={(e) => setHeightCm(e.target.value)}
                />
              </label>
              <label className="field">
                <span className="flabel">{t('settings.field.age')}</span>
                <input
                  type="text"
                  inputMode="numeric"
                  className="input"
                  value={userAge}
                  onChange={(e) => setUserAge(e.target.value)}
                />
              </label>
              <label className="field">
                <span className="flabel">{t('settings.field.sex')}</span>
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

            <label className="field set-mt3">
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

            <label className="field set-mt3">
              <span className="flabel">{t('settings.program')}</span>
              <input
                className="input"
                placeholder={t('settings.program_placeholder')}
                value={userProgram}
                onChange={(e) => setUserProgram(e.target.value)}
              />
              <p className="fhint">{t('settings.program_hint')}</p>
            </label>

            <label className="field set-mt3">
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
          <div className="form">
            <div className="set-fields-grid">
              <label className="field">
                <span className="flabel">{t('settings.field.protein_target')}</span>
                <input
                  type="text"
                  inputMode="numeric"
                  className="input"
                  value={proteinTarget}
                  onChange={(e) => setProteinTarget(e.target.value)}
                />
              </label>
              <label className="field">
                <span className="flabel">{t('settings.field.cal_min')}</span>
                <input
                  type="text"
                  inputMode="numeric"
                  className="input"
                  value={calMin}
                  onChange={(e) => setCalMin(e.target.value)}
                />
              </label>
              <label className="field">
                <span className="flabel">{t('settings.field.cal_max')}</span>
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
              <button type="button" className="ghost" onClick={handleSaveNutrition}>
                {t('settings.save_nutrition')}
              </button>
            </div>
          </div>
        </Section>
      </div>
    </div>
  )
}
