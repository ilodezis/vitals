import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { api, failText, ok } from '@/api/client'
import { restartInNewLanguage } from '@/app/language'
import { OptionGroup } from '@/components/controls/Choices'
import { Section } from '@/components/controls/Section'
import { toast } from '@/components/controls/toast'
import { Icon } from '@/components/icons/Icon'
import { useT } from '@/i18n/useT'
import { cx } from '@/lib/cx'
import type { SettingsView } from './useSettingsView'

interface AppSectionProps {
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

type ModuleInfo = NonNullable<SettingsView['modules']['registry']>[number]

/** Every switchable section, grouped by rubric in the server's order. The list comes from the
 *  registry, not from the navigation: a section that is switched off leaves the navigation, and
 *  it has to stay here or it could never be switched back on. */
export function groupSettingsModules(
  registry: readonly ModuleInfo[] = [],
  enabledModules: Record<string, boolean> = {},
): SettingsModuleGroup[] {
  const groupsByRubric = new Map<string, SettingsModuleItem[]>()
  for (const module of registry) {
    const items = groupsByRubric.get(module.rubric) ?? []
    items.push({
      id: module.key,
      titleKey: `nav.${module.key}`,
      core: module.core,
      enabled: module.core || enabledModules[module.key] === true,
    })
    groupsByRubric.set(module.rubric, items)
  }
  return Array.from(groupsByRubric.entries()).map(([rubric, items]) => ({
    rubric,
    rubricKey: `masthead.rubric.${rubric}`,
    items,
  }))
}

const FALLBACK_ZONES = ['Europe/Chisinau', 'Europe/Moscow', 'Europe/Berlin', 'UTC']

/** The zones the browser knows, with the saved one always among them: a zone missing from the
 *  list would show as another one and be saved over on the next change. */
export function timezoneOptions(saved: string, known: readonly string[] = browserZones()): string[] {
  const zones = known.length > 0 ? [...known] : [...FALLBACK_ZONES]
  if (saved !== '' && !zones.includes(saved)) zones.unshift(saved)
  return zones
}

function browserZones(): string[] {
  try {
    return Intl.supportedValuesOf('timeZone')
  } catch {
    return []
  }
}

/** How the app itself behaves: its language and clock, and which sections it shows. Every
 *  control here applies on the tap — there is nothing to save. */
export function AppSection({ settings }: AppSectionProps) {
  return (
    <>
      <LanguageAndTime settings={settings} />
      <Modules settings={settings} />
    </>
  )
}

function LanguageAndTime({ settings }: AppSectionProps) {
  const { t } = useT()
  const queryClient = useQueryClient()
  const [lang, setLang] = useState(settings.language.language)
  const [timezone, setTimezone] = useState(settings.profile.timezone)

  const changeLanguage = async (next: string) => {
    if (next === lang) return
    const was = lang
    setLang(next)
    try {
      await ok(api.POST('/api/v1/settings/language', { body: { language: next } }))
      toast(t('settings.saved.language'))
      await restartInNewLanguage()
    } catch (err) {
      setLang(was)
      toast(failText(err, t('app.save_failed')), { icon: 'warn' })
    }
  }

  const changeTimezone = async (next: string) => {
    const was = timezone
    setTimezone(next)
    try {
      await ok(api.POST('/api/v1/settings/profile', { body: { timezone: next } }))
      toast(t('settings.saved.timezone'))
      void queryClient.invalidateQueries({ queryKey: ['settings'] })
    } catch (err) {
      setTimezone(was)
      toast(failText(err, t('app.save_failed')), { icon: 'warn' })
    }
  }

  return (
    <Section title={t('settings.region_title')} className="set-sec">
      <div className="form">
        <div className="field">
          <span className="flabel">{t('settings.language_title')}</span>
          <OptionGroup
            label={t('settings.language_title')}
            options={[
              { id: 'ru', label: t('settings.lang_ru') },
              { id: 'en', label: t('settings.lang_en') },
            ]}
            value={lang}
            onChange={(id) => void changeLanguage(id)}
          />
          <p className="fhint">{t('settings.language_description')}</p>
        </div>

        <label className="field set-mt4 set-narrow-select">
          <span className="flabel">{t('settings.timezone')}</span>
          <select className="input" value={timezone} onChange={(e) => void changeTimezone(e.target.value)}>
            {timezoneOptions(settings.profile.timezone).map((zone) => (
              <option key={zone} value={zone}>
                {zone}
              </option>
            ))}
          </select>
          <p className="fhint">{t('settings.timezone_hint')}</p>
        </label>
      </div>
    </Section>
  )
}

function Modules({ settings }: AppSectionProps) {
  const { t } = useT()
  const queryClient = useQueryClient()
  const moduleGroups = groupSettingsModules(settings.modules.registry, settings.modules.enabled_modules)

  const toggle = async (moduleId: string, currentEnabled: boolean) => {
    try {
      await ok(api.POST('/api/v1/settings/modules', { body: { module: moduleId, enabled: !currentEnabled } }))
      toast(t('settings.saved.modules'))
      void queryClient.invalidateQueries({ queryKey: ['settings'] })
      void queryClient.invalidateQueries({ queryKey: ['session'] })
      if (moduleId === 'environment') void queryClient.invalidateQueries({ queryKey: ['environment'] })
    } catch (err) {
      toast(failText(err, t('app.save_failed')), { icon: 'warn' })
    }
  }

  return (
    <Section title={t('modules.title')} className="set-sec">
      <p className="sub set-d">{t('modules.description')}</p>
      <div className="form">
        {moduleGroups.map((group) => (
          <div key={group.rubric} className="mod-g">
            <span className="flabel">{t(group.rubricKey)}</span>
            <div className="opts opts-wrap">
              {group.items.map((it) => (
                <button
                  key={it.id}
                  type="button"
                  className={cx('opt', it.enabled && 'on', it.core && 'lock')}
                  aria-pressed={it.enabled}
                  title={it.core ? t('settings.module_core_title') : undefined}
                  disabled={it.core}
                  onClick={() => void toggle(it.id, it.enabled)}
                >
                  {it.core && <Icon name="lock" />}
                  {t(it.titleKey)}
                </button>
              ))}
            </div>
          </div>
        ))}
      </div>
    </Section>
  )
}
