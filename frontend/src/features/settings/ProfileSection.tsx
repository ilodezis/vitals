import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { api, failText, ok } from '@/api/client'
import { OptionGroup } from '@/components/controls/Choices'
import { Section } from '@/components/controls/Section'
import { toast } from '@/components/controls/toast'
import { useT } from '@/i18n/useT'
import { moduleOn, SaveRow } from './parts'
import type { SettingsView } from './useSettingsView'

interface ProfileSectionProps {
  settings: SettingsView
}

/** Who the owner is: the body the formulas use, the program and goals the reports are written
 *  against, and the day's nutrition targets while nutrition is on. */
export function ProfileSection({ settings }: ProfileSectionProps) {
  return (
    <>
      <AboutYou settings={settings} />
      {moduleOn(settings, 'nutrition') && <NutritionGoals settings={settings} />}
    </>
  )
}

function AboutYou({ settings }: ProfileSectionProps) {
  const { t } = useT()
  const queryClient = useQueryClient()
  const saved = settings.profile

  const [heightCm, setHeightCm] = useState(saved.height_cm)
  const [userAge, setUserAge] = useState(saved.user_age)
  const [sex, setSex] = useState(saved.sex)
  const [userProgram, setUserProgram] = useState(saved.user_program)
  const [userGoals, setUserGoals] = useState(saved.user_goals)

  const dirty =
    heightCm !== saved.height_cm ||
    userAge !== saved.user_age ||
    sex !== saved.sex ||
    userProgram !== saved.user_program ||
    userGoals !== saved.user_goals

  const save = async () => {
    try {
      await ok(api.POST('/api/v1/settings/profile', {
        body: { height_cm: heightCm, user_age: userAge, sex, user_program: userProgram, user_goals: userGoals },
      }))
      toast(t('settings.saved.profile'))
      void queryClient.invalidateQueries({ queryKey: ['settings'] })
      return true
    } catch (err) {
      toast(failText(err, t('app.save_failed')), { icon: 'warn' })
      return false
    }
  }

  return (
    <Section title={t('settings.about_title')} className="set-sec">
      <p className="sub set-d">{t('settings.profile_description')}</p>
      <div className="form">
        <div className="set-fields-grid">
          <label className="field">
            <span className="flabel">{t('settings.field.height')}</span>
            <input type="text" inputMode="numeric" className="input" value={heightCm} onChange={(e) => setHeightCm(e.target.value)} />
          </label>
          <label className="field">
            <span className="flabel">{t('settings.field.age')}</span>
            <input type="text" inputMode="numeric" className="input" value={userAge} onChange={(e) => setUserAge(e.target.value)} />
          </label>
        </div>

        <div className="field set-mt3">
          <span className="flabel">{t('settings.field.sex')}</span>
          <OptionGroup
            label={t('settings.field.sex')}
            options={[
              { id: 'male', label: t('settings.sex_male') },
              { id: 'female', label: t('settings.sex_female') },
            ]}
            value={sex}
            onChange={setSex}
          />
        </div>

        <label className="field set-mt3">
          <span className="flabel">{t('settings.program')}</span>
          <input className="input" placeholder={t('settings.program_placeholder')} value={userProgram} onChange={(e) => setUserProgram(e.target.value)} />
          <p className="fhint">{t('settings.program_hint')}</p>
        </label>

        <label className="field set-mt3">
          <span className="flabel">{t('settings.goals_label')}</span>
          <input className="input" placeholder={t('settings.goals_placeholder')} value={userGoals} onChange={(e) => setUserGoals(e.target.value)} />
          <p className="fhint">{t('settings.goals_hint')}</p>
        </label>

        <SaveRow dirty={dirty} onSave={save}>
          {t('settings.save_profile')}
        </SaveRow>
      </div>
    </Section>
  )
}

function NutritionGoals({ settings }: ProfileSectionProps) {
  const { t } = useT()
  const queryClient = useQueryClient()
  const saved = settings.nutrition_goals

  const [proteinTarget, setProteinTarget] = useState(saved.nutrition_protein_target_g)
  const [calMin, setCalMin] = useState(saved.nutrition_calories_min)
  const [calMax, setCalMax] = useState(saved.nutrition_calories_max)

  const dirty =
    proteinTarget !== saved.nutrition_protein_target_g ||
    calMin !== saved.nutrition_calories_min ||
    calMax !== saved.nutrition_calories_max

  const save = async () => {
    try {
      await ok(api.POST('/api/v1/settings/nutrition', {
        body: { nutrition_protein_target_g: proteinTarget, nutrition_calories_min: calMin, nutrition_calories_max: calMax },
      }))
      toast(t('settings.saved.nutrition'))
      void queryClient.invalidateQueries({ queryKey: ['settings'] })
      return true
    } catch (err) {
      toast(failText(err, t('app.save_failed')), { icon: 'warn' })
      return false
    }
  }

  return (
    <Section title={t('settings.nutrition_title')} className="set-sec">
      <p className="sub set-d">{t('settings.nutrition_hint')}</p>
      <div className="form">
        <div className="set-fields-grid">
          <label className="field">
            <span className="flabel">{t('settings.field.protein_target')}</span>
            <input type="text" inputMode="numeric" className="input" value={proteinTarget} onChange={(e) => setProteinTarget(e.target.value)} />
          </label>
          <label className="field">
            <span className="flabel">{t('settings.field.cal_min')}</span>
            <input type="text" inputMode="numeric" className="input" value={calMin} onChange={(e) => setCalMin(e.target.value)} />
          </label>
          <label className="field">
            <span className="flabel">{t('settings.field.cal_max')}</span>
            <input type="text" inputMode="numeric" className="input" value={calMax} onChange={(e) => setCalMax(e.target.value)} />
          </label>
        </div>
        <SaveRow dirty={dirty} onSave={save}>
          {t('settings.save_nutrition')}
        </SaveRow>
      </div>
    </Section>
  )
}
