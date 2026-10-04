import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useToday } from '@/app/session'
import { failText, api, ok } from '@/api/client'
import { PrimaryButton } from '@/components/controls/PrimaryButton'
import { Section } from '@/components/controls/Section'
import { toast } from '@/components/controls/toast'
import { Icon } from '@/components/icons/Icon'
import { useT } from '@/i18n/useT'
import { cx } from '@/lib/cx'
import { syncedLabel } from '@/lib/dates'
import { formatInt } from '@/lib/format'
import { checkStation, environmentLiveQuery, writeSettings } from './environmentApi'
import { sanitizeThresholds, thresholdFormOf, thresholdPatch, type ThresholdForm } from './thresholds'
import type { EnvSettings, EnvThresholds } from './types'
import { useEnvironmentSettings } from './useEnvironmentData'

interface EnvironmentSettingsProps {
  /** Whether the environment module is on, as the settings say. */
  enabled: boolean
}

/** The station's block in Settings: the module's switch, whether the station answers, the
 *  thresholds that colour the zones and the notifications. */
export function EnvironmentSettings({ enabled }: EnvironmentSettingsProps) {
  const { t } = useT()
  const queryClient = useQueryClient()

  const toggleModule = async () => {
    try {
      await ok(api.POST('/api/v1/settings/modules', { body: { module: 'environment', enabled: !enabled } }))
      toast(t('settings.saved.modules'))
      void queryClient.invalidateQueries({ queryKey: ['settings'] })
      void queryClient.invalidateQueries({ queryKey: ['session'] })
      void queryClient.invalidateQueries({ queryKey: ['environment'] })
    } catch (err) {
      toast(failText(err, t('app.save_failed')), { icon: 'warn' })
    }
  }

  return (
    <Section title={t('settings.env.title')} className="set-sec env-set">
      <p className="sub set-d">{t('settings.env.description')}</p>
      <div className="form">
        <button type="button" className={cx('tgl', enabled && 'on')} aria-pressed={enabled} onClick={() => void toggleModule()}>
          <i />
          {t('settings.env.module')}: {enabled ? t('common.enabled') : t('common.disabled')}
        </button>
        {enabled ? <StationBlock /> : <p className="fhint set-mt2">{t('settings.env.module_off')}</p>}
      </div>
    </Section>
  )
}

function StationBlock() {
  const { t, tOr, lang } = useT()
  const today = useToday()
  const queryClient = useQueryClient()
  const live = useQuery(environmentLiveQuery)
  const settings = useEnvironmentSettings()
  const [checking, setChecking] = useState(false)

  const station = live.data?.station
  const lastSeen = station?.last_seen_at == null ? null : syncedLabel(station.last_seen_at, today, lang)

  const check = async () => {
    setChecking(true)
    try {
      const result = await checkStation()
      toast(
        result.ok ? t('settings.env.check_ok') : tOr(`settings.env.check_error.${result.error ?? ''}`, t('settings.env.check_fail')),
        result.ok ? undefined : { icon: 'warn' },
      )
    } catch (err) {
      toast(failText(err, t('settings.env.check_fail')), { icon: 'warn' })
    } finally {
      setChecking(false)
      void queryClient.invalidateQueries({ queryKey: environmentLiveQuery.queryKey })
    }
  }

  return (
    <>
      <div className="set-sub-sec env-set-station">
        <span className="flabel block strong">{t('settings.env.status')}</span>
        <p className="env-set-line">
          <span className={cx('badge', station?.status === 'online' ? 'good' : station?.status === 'offline' ? 'bad' : 'plain')}>
            {t(`app.env.station.${station?.status ?? 'never'}`)}
          </span>
          {lastSeen !== null && <span className="sub num">{t('settings.env.last_seen', { at: lastSeen })}</span>}
        </p>
        {live.data !== undefined && !live.data.configured && <p className="fhint">{t('settings.env.not_configured')}</p>}
        {(station?.fw != null || station?.rssi != null) && (
          <p className="fhint">
            {[station.fw == null ? null : t('settings.env.firmware', { fw: station.fw }), station.rssi == null ? null : t('app.env.signal', { rssi: formatInt(station.rssi, lang) })]
              .filter(Boolean)
              .join(' · ')}
          </p>
        )}
        <div className="set-mt3">
          <button type="button" className={cx('ghost', checking && 'spin')} disabled={checking || live.data?.configured === false} onClick={() => void check()}>
            <Icon name="sync" />
            <span>{checking ? t('settings.env.checking') : t('settings.env.check')}</span>
          </button>
        </div>
      </div>

      {settings.isError && settings.data === undefined ? (
        <p className="fhint set-mt3">{t('settings.env.failed')}</p>
      ) : settings.data === undefined ? null : (
        <SettingsForm settings={settings.data} />
      )}
    </>
  )
}

/** The thresholds and the two notification switches of one read of the settings. */
function SettingsForm({ settings }: { settings: EnvSettings }) {
  const { t } = useT()
  const queryClient = useQueryClient()
  const [form, setForm] = useState<ThresholdForm>(() => thresholdFormOf(settings))
  const [alertsEnabled, setAlertsEnabled] = useState(settings.alerts_enabled)
  const [alertTelegram, setAlertTelegram] = useState(settings.alert_telegram)

  const stored = (next: EnvSettings) => {
    queryClient.setQueryData(['environment', 'settings'], next)
    void queryClient.invalidateQueries({ queryKey: ['environment', 'live'] })
    void queryClient.invalidateQueries({ queryKey: ['environment', 'series'] })
    void queryClient.invalidateQueries({ queryKey: ['environment', 'night'] })
  }

  const saveThresholds = async (): Promise<boolean> => {
    const parsed = sanitizeThresholds(form)
    if (parsed === 'number') {
      toast(t('settings.env.number_error'), { icon: 'warn' })
      return false
    }
    if (parsed === 'order') {
      toast(t('settings.env.order_error'), { icon: 'warn' })
      return false
    }
    try {
      const saved = await writeSettings(thresholdPatch(parsed))
      setForm(thresholdFormOf(saved))
      stored(saved)
      toast(t('settings.saved.environment'))
      return true
    } catch (err) {
      toast(failText(err, t('app.save_failed')), { icon: 'warn' })
      return false
    }
  }

  const flip = async (key: 'alerts_enabled' | 'alert_telegram') => {
    const set = key === 'alerts_enabled' ? setAlertsEnabled : setAlertTelegram
    const was = key === 'alerts_enabled' ? alertsEnabled : alertTelegram
    set(!was)
    try {
      const saved = await writeSettings({ [key]: !was })
      stored(saved)
    } catch (err) {
      set(was)
      toast(failText(err, t('app.save_failed')), { icon: 'warn' })
    }
  }

  const field = (key: keyof EnvThresholds, label: string, decimal = false) => (
    <label className="field" key={key}>
      <span className="flabel">{label}</span>
      <input
        type="text"
        inputMode={decimal ? 'decimal' : 'numeric'}
        className="input"
        value={form[key]}
        onChange={(e) => setForm({ ...form, [key]: e.target.value })}
      />
    </label>
  )
  const from = t('settings.env.from')
  const to = t('settings.env.to')

  return (
    <>
      <div className="set-sub-sec">
        <span className="flabel block strong">{t('settings.env.thresholds')}</span>
        <p className="fhint">{t('settings.env.thresholds_hint')}</p>

        <div className="env-th">
          <span className="flabel">{t('settings.env.co2')}</span>
          <div className="env-th-grid n3">
            {field('co2_ok_max', t('settings.env.co2_ok_max'))}
            {field('co2_warn', t('settings.env.co2_warn'))}
            {field('co2_bad', t('settings.env.co2_bad'))}
          </div>
        </div>
        <div className="env-th">
          <span className="flabel">{t('settings.env.temp_day')}</span>
          <div className="env-th-grid">
            {field('temp_day_min', from, true)}
            {field('temp_day_max', to, true)}
          </div>
        </div>
        <div className="env-th">
          <span className="flabel">{t('settings.env.temp_sleep')}</span>
          <div className="env-th-grid">
            {field('temp_sleep_min', from, true)}
            {field('temp_sleep_max', to, true)}
          </div>
        </div>
        <div className="env-th">
          <span className="flabel">{t('settings.env.rh_comfort')}</span>
          <div className="env-th-grid">
            {field('rh_min', from)}
            {field('rh_max', to)}
          </div>
        </div>
        <div className="env-th">
          <span className="flabel">{t('settings.env.rh_alert')}</span>
          <div className="env-th-grid">
            {field('rh_alert_low', from)}
            {field('rh_alert_high', to)}
          </div>
        </div>

        <div className="set-save">
          <PrimaryButton onPress={saveThresholds}>{t('settings.env.save_thresholds')}</PrimaryButton>
        </div>
      </div>

      <div className="set-sub-sec">
        <span className="flabel block strong">{t('settings.env.notifications')}</span>
        <button type="button" className={cx('tgl', alertsEnabled && 'on')} aria-pressed={alertsEnabled} onClick={() => void flip('alerts_enabled')}>
          <i />
          {t('settings.env.alerts_enabled')}
        </button>
        <p className="fhint">{t('settings.env.alerts_hint')}</p>
        <button
          type="button"
          className={cx('tgl', alertTelegram && 'on')}
          aria-pressed={alertTelegram}
          disabled={!alertsEnabled}
          onClick={() => void flip('alert_telegram')}
        >
          <i />
          {t('settings.env.alert_telegram')}
        </button>
        <p className="fhint">{t('settings.env.alert_telegram_hint')}</p>
      </div>
    </>
  )
}
