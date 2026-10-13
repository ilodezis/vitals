import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { api, failText, ok } from '@/api/client'
import { Alert, type AlertTone } from '@/components/controls/Alert'
import { Disclosure } from '@/components/controls/Disclosure'
import { Section } from '@/components/controls/Section'
import { toast } from '@/components/controls/toast'
import { Icon } from '@/components/icons/Icon'
import { useToday } from '@/app/session'
import { EnvironmentSettings } from '@/features/environment/EnvironmentSettings'
import { useT } from '@/i18n/useT'
import { cx } from '@/lib/cx'
import { longDate, parseIsoDate, syncedLabel } from '@/lib/dates'
import { formatCompact } from '@/lib/format'
import { ConnectedBadge, moduleOn, SaveRow } from './parts'
import { readProactiveNumbers, type ProactiveNumberKey } from './proactiveBody'
import type { SettingsView } from './useSettingsView'

interface ConnectionsSectionProps {
  settings: SettingsView
}

/** How the export's state reads: a done export is plain news, a stuck or refused one a warning,
 *  nothing queued yet a quiet note. */
export function exportTone(status: string | null | undefined): AlertTone {
  if (status === 'failed' || status === 'conflict' || status === 'unverified' || status === 'delete_failed') return 'warn'
  if (status == null || status === '' || status === 'skipped') return 'note'
  return 'info'
}

const SEND_NOW_WORDED = new Set(['sent', 'matched', 'deleted', 'empty', 'disabled', 'unconfigured', 'busy', 'error'])
const SEND_NOW_REFUSED = new Set(['disabled', 'unconfigured', 'busy', 'error'])

/** What one "send now" run is reported as. An outcome without wording of its own points at the
 *  status card, which already shows it. */
export function sendNowOutcome(status: string): { key: string; warn: boolean } {
  return {
    key: `settings.garmin_weight_action.${SEND_NOW_WORDED.has(status) ? status : 'done'}`,
    warn: SEND_NOW_REFUSED.has(status) || exportTone(status) === 'warn',
  }
}

/** Every outside service on one tab, each in its own block with its state in the heading:
 *  the data sources first, then the AI and the Claude connector. */
export function ConnectionsSection({ settings }: ConnectionsSectionProps) {
  const hasStation = settings.modules.registry?.some((m) => m.key === 'environment') === true
  return (
    <>
      <GarminCard settings={settings} />
      {moduleOn(settings, 'hevy') && <HevyCard settings={settings} />}
      {hasStation && <EnvironmentSettings enabled={moduleOn(settings, 'environment')} />}
      <AiCard settings={settings} />
      <ClaudeCard settings={settings} />
    </>
  )
}

function useSave() {
  const { t } = useT()
  const queryClient = useQueryClient()
  return async (request: () => Promise<unknown>, savedKey: string, after?: () => void) => {
    try {
      await request()
      toast(t(savedKey))
      after?.()
      void queryClient.invalidateQueries({ queryKey: ['settings'] })
      return true
    } catch (err) {
      toast(failText(err, t('app.save_failed')), { icon: 'warn' })
      return false
    }
  }
}

/** A secret is never read back: the field stays empty and the label says whether one is set. */
function SecretField({ label, isSet, value, onChange, placeholder }: { label: string; isSet: boolean; value: string; onChange: (v: string) => void; placeholder?: string }) {
  const { t } = useT()
  return (
    <label className="field">
      <span className="flabel split">
        <span>{label}</span>
        <span className={cx('badge', isSet && 'good')}>{isSet ? t('settings.key_set') : t('settings.key_not_set')}</span>
      </span>
      <input
        type="password"
        className="input"
        placeholder={placeholder ?? (isSet ? t('settings.key_placeholder_set') : '')}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
    </label>
  )
}

function GarminCard({ settings }: ConnectionsSectionProps) {
  const { t } = useT()
  const save = useSave()
  const garmin = settings.garmin
  const [email, setEmail] = useState(garmin.garmin_email)
  const [password, setPassword] = useState('')
  const breaker = garmin.breaker as { used?: number; max?: number; paused?: boolean } | null

  const saveAccount = () =>
    save(
      () => ok(api.POST('/api/v1/settings/garmin', { body: { garmin_email: email.trim() || undefined, garmin_password: password.trim() || undefined } })),
      'settings.saved.garmin',
      () => setPassword(''),
    )

  return (
    <Section title={t('settings.garmin_title')} meta={<ConnectedBadge ok={garmin.garmin_credentials_configured} />} className="set-sec">
      <p className="sub set-d">{t('settings.garmin_description')}</p>
      <div className="form">
        {breaker?.paused === true && (
          <Alert tone="warn" className="set-mb3">
            {t('settings.breaker_paused', { used: breaker.used ?? '—', max: breaker.max ?? 10 })}
          </Alert>
        )}
        <div className="set-grid-2">
          <label className="field">
            <span className="flabel">{t('settings.garmin_email')}</span>
            <input type="email" className="input" value={email} onChange={(e) => setEmail(e.target.value)} />
          </label>
          <SecretField
            label={t('settings.garmin_password')}
            isSet={garmin.garmin_password_set}
            value={password}
            onChange={setPassword}
            placeholder={garmin.garmin_password_set ? t('settings.garmin_password_placeholder_set') : t('settings.garmin_password_placeholder')}
          />
        </div>
        <SaveRow dirty={email !== garmin.garmin_email || password !== ''} onSave={saveAccount}>
          {t('settings.save_garmin')}
        </SaveRow>

        <WeightExport settings={settings} />
        <GarminSchedule settings={settings} />
      </div>
    </Section>
  )
}

function WeightExport({ settings }: ConnectionsSectionProps) {
  const { t, tOr, lang } = useT()
  const today = useToday()
  const queryClient = useQueryClient()
  const garmin = settings.garmin
  const [enabled, setEnabled] = useState(garmin.garmin_weight_export_enabled)

  const status = garmin.garmin_weight_status as {
    status?: string | null
    date?: string | null
    weight_kg?: number | null
    next_attempt_at?: string | null
    last_error?: string | null
  } | null
  const tone = exportTone(status?.status)

  const toggle = async () => {
    const next = !enabled
    try {
      await ok(api.POST('/api/v1/settings/garmin/weight-toggle', { body: { enabled: next } }))
      setEnabled(next)
      toast(next ? t('settings.garmin_weight_action.toggle_enabled') : t('settings.garmin_weight_action.toggle_disabled'))
      void queryClient.invalidateQueries({ queryKey: ['settings'] })
    } catch (err) {
      toast(failText(err, t('app.save_failed')), { icon: 'warn' })
    }
  }

  const sendNow = async () => {
    try {
      toast(t('settings.garmin_weight_action.manual_sync_started'))
      const result = await ok(api.POST('/api/v1/settings/garmin/weight/send-now'))
      const outcome = sendNowOutcome(result.status)
      toast(t(outcome.key), outcome.warn ? { icon: 'warn' } : undefined)
      void queryClient.invalidateQueries({ queryKey: ['settings'] })
    } catch (err) {
      toast(failText(err, t('app.save_failed')), { icon: 'warn' })
    }
  }

  return (
    <div className="set-sub-sec">
      <span className="flabel block strong">{t('settings.garmin_weight_export_label')}</span>
      <button type="button" className={cx('tgl', enabled && 'on')} aria-pressed={enabled} onClick={() => void toggle()}>
        <i />
        {enabled ? t('common.enabled') : t('common.disabled')}
      </button>
      <p className="fhint set-mt2">{t('settings.garmin_weight_export_hint')}</p>
      {!garmin.garmin_credentials_configured && <p className="fhint set-mt2">{t('settings.garmin_weight_credentials_missing')}</p>}

      {enabled && (
        <>
          <Alert tone={tone} icon={tone === 'info' ? 'check' : undefined} className="set-mt3">
            <div>
              {status?.status
                ? tOr(`settings.garmin_weight_status.${status.status}`, status.status, {
                    weight: status.weight_kg == null ? '—' : formatCompact(status.weight_kg, lang),
                    date: status.date ? longDate(parseIsoDate(status.date), lang) : '—',
                  })
                : t('settings.garmin_weight_status.empty')}
            </div>
            {status?.last_error ? (
              <span className="set-note">
                {t('settings.garmin_weight_last_error')}: {status.last_error}
              </span>
            ) : null}
            {Boolean(status?.next_attempt_at) && (
              <span className="set-note">
                {t('settings.garmin_weight_next_attempt', { at: syncedLabel(String(status?.next_attempt_at), today, lang) })}
              </span>
            )}
          </Alert>
          <div className="set-mt3">
            <button type="button" className="ghost" onClick={() => void sendNow()}>
              <Icon name="upload" />
              <span>{t('settings.garmin_weight_send_now')}</span>
            </button>
          </div>
        </>
      )}
    </div>
  )
}

type ScheduleKey = Extract<ProactiveNumberKey, 'syncHours' | 'pulseSeconds' | 'pulseStartHour' | 'pulseEndHour' | 'weightExportMinutes' | 'weightMaxAgeDays'>

const SCHEDULE_LABELS: Record<ScheduleKey, string> = {
  syncHours: 'settings.sync_hours',
  pulseSeconds: 'settings.pulse_seconds',
  pulseStartHour: 'settings.pulse_start_hour',
  pulseEndHour: 'settings.pulse_end_hour',
  weightExportMinutes: 'settings.weight_export_minutes',
  weightMaxAgeDays: 'settings.weight_max_age_days',
}

/** How often Garmin is read and written, folded away: the defaults are the safe ones, and the
 *  summary in the header tells what they are without opening it. */
function GarminSchedule({ settings }: ConnectionsSectionProps) {
  const { t } = useT()
  const save = useSave()
  const p = settings.proactive
  const savedFields: Record<ScheduleKey, string> = {
    syncHours: String(p.garmin_sync_hours),
    pulseSeconds: String(p.pulse_seconds),
    pulseStartHour: String(p.pulse_start_hour),
    pulseEndHour: String(p.pulse_end_hour),
    weightExportMinutes: String(p.garmin_weight_export_minutes),
    weightMaxAgeDays: String(p.garmin_weight_max_age_days),
  }
  const [open, setOpen] = useState(false)
  const [fields, setFields] = useState(savedFields)
  const dirty = (Object.keys(fields) as ScheduleKey[]).some((key) => fields[key] !== savedFields[key])
  const breaker = settings.garmin.breaker as { used?: number; max?: number; paused?: boolean } | null

  const saveSchedule = async () => {
    const read = readProactiveNumbers(fields)
    if (!read.ok) {
      const names = read.invalid.map((key) => t(SCHEDULE_LABELS[key as ScheduleKey])).join(', ')
      toast(t('settings.proactive_invalid', { fields: names }), { icon: 'warn' })
      return false
    }
    return save(() => ok(api.POST('/api/v1/settings/proactive', { body: read.numbers })), 'settings.saved.garmin_schedule')
  }

  const input = (key: ScheduleKey, hint: string) => (
    <label className="field" key={key}>
      <span className="flabel">{t(SCHEDULE_LABELS[key])}</span>
      <input type="text" inputMode="numeric" className="input" value={fields[key]} onChange={(e) => setFields({ ...fields, [key]: e.target.value })} />
      <p className="fhint">{t(hint)}</p>
    </label>
  )

  const summary =
    p.pulse_seconds === 0
      ? t('settings.garmin_schedule_summary_nopulse', { hours: p.garmin_sync_hours })
      : t('settings.garmin_schedule_summary', { hours: p.garmin_sync_hours, seconds: p.pulse_seconds })

  return (
    <Disclosure className="set-disc" open={open} onToggle={() => setOpen(!open)} title={t('settings.garmin_schedule_label')} sub={summary}>
      <div className="disc-body">
        <p className="fhint set-mb3">{t('settings.garmin_schedule_hint')}</p>
        <div className="set-garmin-grid">
          {input('syncHours', 'settings.sync_hours_hint')}
          {input('pulseSeconds', 'settings.pulse_seconds_hint')}
          {input('pulseStartHour', 'settings.pulse_start_hour_hint')}
          {input('pulseEndHour', 'settings.pulse_end_hour_hint')}
          {input('weightExportMinutes', 'settings.weight_export_minutes_hint')}
          {input('weightMaxAgeDays', 'settings.weight_max_age_days_hint')}
        </div>

        {/* A paused breaker is already shown at the top of the card. */}
        {breaker !== null && breaker.paused !== true && (
          <Alert tone="note" className="set-mt3">
            <b>{t('settings.garmin_breaker')}</b>
            <span className="set-note">
              {breaker.used !== undefined ? t('settings.breaker_status', { used: breaker.used, max: breaker.max ?? 10 }) : t('settings.breaker_unknown')}
            </span>
          </Alert>
        )}

        <SaveRow dirty={dirty} onSave={saveSchedule}>
          {t('settings.save_garmin_schedule')}
        </SaveRow>
      </div>
    </Disclosure>
  )
}

function HevyCard({ settings }: ConnectionsSectionProps) {
  const { t } = useT()
  const save = useSave()
  const [key, setKey] = useState('')
  const saveKey = () =>
    save(() => ok(api.POST('/api/v1/settings/hevy', { body: { hevy_api_key: key.trim() || undefined } })), 'settings.saved.hevy', () => setKey(''))

  return (
    <Section title={t('settings.hevy_title')} meta={<ConnectedBadge ok={settings.hevy.hevy_api_key_set} />} className="set-sec">
      <p className="sub set-d">{t('settings.hevy_description')}</p>
      <div className="form">
        <SecretField label={t('settings.hevy_key')} isSet={settings.hevy.hevy_api_key_set} value={key} onChange={setKey} />
        <SaveRow dirty={key.trim() !== ''} onSave={saveKey}>
          {t('settings.save_hevy')}
        </SaveRow>
      </div>
    </Section>
  )
}

function AiCard({ settings }: ConnectionsSectionProps) {
  const { t } = useT()
  const save = useSave()
  const ai = settings.ai
  const [open, setOpen] = useState(false)
  const [apiKey, setApiKey] = useState('')
  const [digestModel, setDigestModel] = useState(ai.llm_model_digest)
  const [parserModel, setParserModel] = useState(ai.llm_model_parser)
  const [briefModel, setBriefModel] = useState(ai.llm_model_brief)
  const [baseUrl, setBaseUrl] = useState(ai.openrouter_base_url)

  const dirty =
    apiKey.trim() !== '' ||
    digestModel !== ai.llm_model_digest ||
    parserModel !== ai.llm_model_parser ||
    briefModel !== ai.llm_model_brief ||
    baseUrl !== ai.openrouter_base_url

  const saveAi = () =>
    save(
      () =>
        ok(api.POST('/api/v1/settings/ai', {
          body: {
            openrouter_api_key: apiKey.trim() || undefined,
            openrouter_base_url: baseUrl.trim() || undefined,
            llm_model_digest: digestModel.trim() || undefined,
            llm_model_parser: parserModel.trim() || undefined,
            llm_model_brief: briefModel.trim() || undefined,
          },
        })),
      'settings.saved.ai',
      () => setApiKey(''),
    )

  const model = (label: string, value: string, set: (v: string) => void, hint: string, placeholder?: string) => (
    <label className="field">
      <span className="flabel">{t(label)}</span>
      <input className="input" placeholder={placeholder} value={value} onChange={(e) => set(e.target.value)} />
      <p className="fhint">{t(hint)}</p>
    </label>
  )

  return (
    <Section title={t('settings.ai_title')} meta={<ConnectedBadge ok={ai.openrouter_api_key_set} />} className="set-sec">
      <p className="sub set-d">{t('settings.ai_description')}</p>
      <div className="form">
        <SecretField label={t('settings.api_key')} isSet={ai.openrouter_api_key_set} value={apiKey} onChange={setApiKey} />

        <Disclosure className="set-disc" open={open} onToggle={() => setOpen(!open)} title={t('settings.ai_models_title')} sub={ai.llm_model_digest}>
          <div className="disc-body set-stack3">
            {model('settings.digest_model', digestModel, setDigestModel, 'settings.digest_model_hint')}
            {model('settings.parser_model', parserModel, setParserModel, 'settings.parser_model_hint')}
            {model('settings.brief_model', briefModel, setBriefModel, 'settings.brief_model_hint', t('settings.brief_model_placeholder'))}
            <label className="field">
              <span className="flabel">{t('settings.base_url')}</span>
              <input className="input" placeholder="https://…" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} />
            </label>
          </div>
        </Disclosure>

        <SaveRow dirty={dirty} onSave={saveAi}>
          {t('settings.save_ai')}
        </SaveRow>
      </div>
    </Section>
  )
}

function ClaudeCard({ settings }: ConnectionsSectionProps) {
  const { t } = useT()
  const save = useSave()
  const mcp = settings.mcp
  const [clientId, setClientId] = useState(mcp.mcp_client_id)
  const [secret, setSecret] = useState('')

  const saveMcp = () =>
    save(
      () => ok(api.POST('/api/v1/settings/mcp', { body: { mcp_client_id: clientId.trim() || undefined, mcp_client_secret: secret.trim() || undefined } })),
      'settings.saved.mcp',
      () => setSecret(''),
    )

  return (
    <Section title={t('settings.mcp_title')} meta={<ConnectedBadge ok={mcp.mcp_client_secret_set} />} className="set-sec">
      <p className="sub set-d">{t('settings.mcp_description')}</p>
      <div className="form">
        <div className="set-grid-2">
          <label className="field">
            <span className="flabel">{t('settings.mcp_id')}</span>
            <input className="input" value={clientId} onChange={(e) => setClientId(e.target.value)} />
          </label>
          <SecretField label={t('settings.mcp_secret')} isSet={mcp.mcp_client_secret_set} value={secret} onChange={setSecret} placeholder={t('settings.mcp_secret_placeholder')} />
        </div>
        <SaveRow dirty={clientId !== mcp.mcp_client_id || secret.trim() !== ''} onSave={saveMcp}>
          {t('settings.save_mcp')}
        </SaveRow>
      </div>
    </Section>
  )
}
