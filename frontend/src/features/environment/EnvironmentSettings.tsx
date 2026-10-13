import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useToday } from '@/app/session'
import { failText, api, ok } from '@/api/client'
import { Disclosure } from '@/components/controls/Disclosure'
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
// Settings can be the first screen opened, before the station's own screen has loaded this.
import './environment.css'

interface EnvironmentSettingsProps {
  /** Whether the environment module is on, as the settings say. */
  enabled: boolean
}

/** The station's block among the connections: the module's switch, whether the station answers
 *  and the thresholds that colour the zones. Its notifications live with the bot's
 *  (`EnvironmentAlerts`). */
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
    <Section
      title={t('settings.env.title')}
      meta={enabled ? <StationBadge /> : <span className="badge">{t('common.disabled')}</span>}
      className="set-sec env-set"
    >
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

/** Whether the station answers, in the block's heading like every other connection's state. */
function StationBadge() {
  const { t } = useT()
  const status = useQuery(environmentLiveQuery).data?.station?.status
  return <span className={cx('badge', status === 'online' ? 'good' : status === 'offline' ? 'bad' : undefined)}>{t(`app.env.station.${status ?? 'never'}`)}</span>
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
        {/* Its state is in the block's heading; here only when it was last heard from. */}
        {lastSeen !== null && (
          <p className="env-set-line">
            <span className="sub num">{t('settings.env.last_seen', { at: lastSeen })}</span>
          </p>
        )}
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

/** Keeps the cache in step with a saved write: the zones, the night and the live card all read
 *  the thresholds. */
function useStoreSettings() {
  const queryClient = useQueryClient()
  return (next: EnvSettings) => {
    queryClient.setQueryData(['environment', 'settings'], next)
    void queryClient.invalidateQueries({ queryKey: ['environment', 'live'] })
    void queryClient.invalidateQueries({ queryKey: ['environment', 'series'] })
    void queryClient.invalidateQueries({ queryKey: ['environment', 'night'] })
  }
}

/** The thresholds of one read of the settings, folded away: they are set once and rarely
 *  touched again. */
function SettingsForm({ settings }: { settings: EnvSettings }) {
  const { t } = useT()
  const stored = useStoreSettings()
  const [open, setOpen] = useState(false)
  const [form, setForm] = useState<ThresholdForm>(() => thresholdFormOf(settings))
  const dirty = JSON.stringify(form) !== JSON.stringify(thresholdFormOf(settings))

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
    <Disclosure className="set-disc" open={open} onToggle={() => setOpen(!open)} title={t('settings.env.thresholds')} sub={t('settings.env.thresholds_hint')}>
      <div className="disc-body">
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
          <PrimaryButton disabled={!dirty} onPress={saveThresholds}>
            {t('settings.env.save_thresholds')}
          </PrimaryButton>
        </div>
      </div>
    </Disclosure>
  )
}

/** The station's notifications, shown among the bot's other ones: whether a bad reading raises
 *  an alert, and whether that alert is also sent to Telegram. */
export function EnvironmentAlerts() {
  const { t } = useT()
  const settings = useEnvironmentSettings()
  return (
    <Section title={t('settings.env.alerts_title')} className="set-sec env-set">
      {settings.isError && settings.data === undefined ? (
        <p className="fhint">{t('settings.env.failed')}</p>
      ) : settings.data === undefined ? null : (
        <AlertSwitches settings={settings.data} />
      )}
    </Section>
  )
}

function AlertSwitches({ settings }: { settings: EnvSettings }) {
  const { t } = useT()
  const stored = useStoreSettings()
  const [alertsEnabled, setAlertsEnabled] = useState(settings.alerts_enabled)
  const [alertTelegram, setAlertTelegram] = useState(settings.alert_telegram)

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

  return (
    <div className="set-switches">
      <div className="set-switch">
        <button type="button" className={cx('tgl', alertsEnabled && 'on')} aria-pressed={alertsEnabled} onClick={() => void flip('alerts_enabled')}>
          <i />
          {t('settings.env.alerts_enabled')}
        </button>
        <p className="fhint">{t('settings.env.alerts_hint')}</p>
      </div>
      <div className="set-switch">
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
    </div>
  )
}
