import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { api, failText, ok } from '@/api/client'
import { Alert, type AlertTone } from '@/components/controls/Alert'
import { Section } from '@/components/controls/Section'
import { toast } from '@/components/controls/toast'
import { Icon } from '@/components/icons/Icon'
import { useToday } from '@/app/session'
import { useT } from '@/i18n/useT'
import { cx } from '@/lib/cx'
import { longDate, parseIsoDate, syncedLabel } from '@/lib/dates'
import { formatCompact } from '@/lib/format'
import { HealthImport } from './HealthImport'
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

export function ConnectionsSection({ settings }: ConnectionsSectionProps) {
  const { t, tOr, lang } = useT()
  const today = useToday()
  const queryClient = useQueryClient()

  // AI form state
  const [apiKey, setApiKey] = useState('')
  const [digestModel, setDigestModel] = useState(settings.ai.llm_model_digest)
  const [parserModel, setParserModel] = useState(settings.ai.llm_model_parser)
  const [briefModel, setBriefModel] = useState(settings.ai.llm_model_brief)
  const [baseUrl, setBaseUrl] = useState(settings.ai.openrouter_base_url)

  // Hevy state
  const [hevyKey, setHevyKey] = useState('')

  // Garmin state
  const [garminEmail, setGarminEmail] = useState(settings.garmin.garmin_email)
  const [garminPassword, setGarminPassword] = useState('')
  const [weightExportEnabled, setWeightExportEnabled] = useState(settings.garmin.garmin_weight_export_enabled)

  // MCP state
  const [mcpClientId, setMcpClientId] = useState(settings.mcp.mcp_client_id)
  const [mcpClientSecret, setMcpClientSecret] = useState('')

  // Save AI
  const handleSaveAi = async () => {
    try {
      await ok(api.POST('/api/v1/settings/ai', {
        body: {
          openrouter_api_key: apiKey.trim() || undefined,
          openrouter_base_url: baseUrl.trim() || undefined,
          llm_model_digest: digestModel.trim() || undefined,
          llm_model_parser: parserModel.trim() || undefined,
          llm_model_brief: briefModel.trim() || undefined,
        },
      }))
      toast(t('settings.saved.ai'))
      setApiKey('')
      void queryClient.invalidateQueries({ queryKey: ['settings'] })
      return true
    } catch (err) {
      toast(failText(err, t('app.save_failed')), { icon: 'warn' })
      return false
    }
  }

  // Save Hevy
  const handleSaveHevy = async () => {
    try {
      await ok(api.POST('/api/v1/settings/hevy', {
        body: {
          hevy_api_key: hevyKey.trim() || undefined,
        },
      }))
      toast(t('settings.saved.hevy'))
      setHevyKey('')
      void queryClient.invalidateQueries({ queryKey: ['settings'] })
      return true
    } catch (err) {
      toast(failText(err, t('app.save_failed')), { icon: 'warn' })
      return false
    }
  }

  // Save Garmin credentials
  const handleSaveGarmin = async () => {
    try {
      await ok(api.POST('/api/v1/settings/garmin', {
        body: {
          garmin_email: garminEmail.trim() || undefined,
          garmin_password: garminPassword.trim() || undefined,
        },
      }))
      toast(t('settings.saved.garmin'))
      setGarminPassword('')
      void queryClient.invalidateQueries({ queryKey: ['settings'] })
      return true
    } catch (err) {
      toast(failText(err, t('app.save_failed')), { icon: 'warn' })
      return false
    }
  }

  // Toggle Garmin weight export
  const handleToggleWeightExport = async () => {
    const next = !weightExportEnabled
    try {
      await ok(api.POST('/api/v1/settings/garmin/weight-toggle', {
        body: { enabled: next },
      }))
      setWeightExportEnabled(next)
      toast(
        next
          ? t('settings.garmin_weight_action.toggle_enabled')
          : t('settings.garmin_weight_action.toggle_disabled')
      )
      void queryClient.invalidateQueries({ queryKey: ['settings'] })
    } catch (err) {
      toast(failText(err, t('app.save_failed')), { icon: 'warn' })
    }
  }

  // Send weight to Garmin now
  const handleSendWeightNow = async () => {
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

  // Save MCP credentials
  const handleSaveMcp = async () => {
    try {
      await ok(api.POST('/api/v1/settings/mcp', {
        body: {
          mcp_client_id: mcpClientId.trim() || undefined,
          mcp_client_secret: mcpClientSecret.trim() || undefined,
        },
      }))
      toast(t('settings.saved.mcp'))
      setMcpClientSecret('')
      void queryClient.invalidateQueries({ queryKey: ['settings'] })
      return true
    } catch (err) {
      toast(failText(err, t('app.save_failed')), { icon: 'warn' })
      return false
    }
  }

  const weightStatus = settings.garmin.garmin_weight_status as {
    status?: string | null
    date?: string | null
    weight_kg?: number | null
    next_attempt_at?: string | null
    last_error?: string | null
  } | null

  return (
    <div className="grid">
      <div className="c6">
        {/* OpenRouter AI */}
        <Section title={t('settings.ai_title')} className="set-sec">
          <p className="sub set-d">{t('settings.ai_description')}</p>
          <div className="form">
            <label className="field">
              <span className="flabel split">
                <span>{t('settings.api_key')}</span>
                <span className={`badge ${settings.ai.openrouter_api_key_set ? 'good' : ''}`}>
                  {settings.ai.openrouter_api_key_set ? t('settings.key_set') : t('settings.key_not_set')}
                </span>
              </span>
              <input
                type="password"
                className="input"
                placeholder={settings.ai.openrouter_api_key_set ? t('settings.key_placeholder_set') : ''}
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
              />
            </label>

            <label className="field">
              <span className="flabel">{t('settings.digest_model')}</span>
              <input
                className="input"
                value={digestModel}
                onChange={(e) => setDigestModel(e.target.value)}
              />
              <p className="fhint">{t('settings.digest_model_hint')}</p>
            </label>

            <label className="field">
              <span className="flabel">{t('settings.parser_model')}</span>
              <input
                className="input"
                value={parserModel}
                onChange={(e) => setParserModel(e.target.value)}
              />
              <p className="fhint">{t('settings.parser_model_hint')}</p>
            </label>

            <label className="field">
              <span className="flabel">{t('settings.brief_model')}</span>
              <input
                className="input"
                placeholder={t('settings.brief_model_placeholder')}
                value={briefModel}
                onChange={(e) => setBriefModel(e.target.value)}
              />
              <p className="fhint">{t('settings.brief_model_hint')}</p>
            </label>

            <label className="field">
              <span className="flabel">{t('settings.base_url')}</span>
              <input
                className="input"
                placeholder="https://…"
                value={baseUrl}
                onChange={(e) => setBaseUrl(e.target.value)}
              />
            </label>

            <div className="set-save">
              <button type="button" className="ghost" onClick={handleSaveAi}>
                {t('settings.save_ai')}
              </button>
            </div>
          </div>
        </Section>

        {/* Hevy */}
        <Section title={t('settings.hevy_title')} className="set-sec">
          <p className="sub set-d">{t('settings.hevy_description')}</p>
          <div className="form">
            <label className="field">
              <span className="flabel split">
                <span>{t('settings.hevy_key')}</span>
                <span className={`badge ${settings.hevy.hevy_api_key_set ? 'good' : ''}`}>
                  {settings.hevy.hevy_api_key_set ? t('settings.key_set') : t('settings.key_not_set')}
                </span>
              </span>
              <input
                type="password"
                className="input"
                placeholder={settings.hevy.hevy_api_key_set ? t('settings.key_placeholder_set') : ''}
                value={hevyKey}
                onChange={(e) => setHevyKey(e.target.value)}
              />
            </label>

            <div className="set-save">
              <button type="button" className="ghost" onClick={handleSaveHevy}>
                {t('settings.save_hevy')}
              </button>
            </div>
          </div>
        </Section>
      </div>

      <div className="c6">
        {/* Garmin Connect */}
        <Section title={t('settings.garmin_title')} className="set-sec">
          <p className="sub set-d">{t('settings.garmin_description')}</p>
          <div className="form">
            <div className="set-grid-2">
              <label className="field">
                <span className="flabel">{t('settings.garmin_email')}</span>
                <input
                  type="email"
                  className="input"
                  value={garminEmail}
                  onChange={(e) => setGarminEmail(e.target.value)}
                />
              </label>
              <label className="field">
                <span className="flabel split">
                  <span>{t('settings.garmin_password')}</span>
                  <span className={`badge ${settings.garmin.garmin_password_set ? 'good' : ''}`}>
                    {settings.garmin.garmin_password_set ? t('settings.key_set') : t('settings.key_not_set')}
                  </span>
                </span>
                <input
                  type="password"
                  className="input"
                  placeholder={settings.garmin.garmin_password_set ? t('settings.garmin_password_placeholder_set') : t('settings.garmin_password_placeholder')}
                  value={garminPassword}
                  onChange={(e) => setGarminPassword(e.target.value)}
                />
              </label>
            </div>

            <div className="set-save">
              <button type="button" className="ghost" onClick={handleSaveGarmin}>
                {t('settings.save_garmin')}
              </button>
            </div>

            {/* Garmin Weight Export */}
            <div className="set-sub-sec">
              <span className="flabel block strong">
                {t('settings.garmin_weight_export_label')}
              </span>
              <button
                type="button"
                className={cx('tgl', weightExportEnabled && 'on')}
                aria-pressed={weightExportEnabled}
                onClick={handleToggleWeightExport}
              >
                <i />
                {weightExportEnabled ? t('common.enabled') : t('common.disabled')}
              </button>
              <p className="fhint set-mt2">{t('settings.garmin_weight_export_hint')}</p>

              <p className="fhint set-mt2">
                {settings.garmin.garmin_credentials_configured
                  ? t('settings.garmin_weight_credentials_ready')
                  : t('settings.garmin_weight_credentials_missing')}
              </p>

              <Alert tone={exportTone(weightStatus?.status)} icon={exportTone(weightStatus?.status) === 'info' ? 'check' : undefined} className="set-mt3">
                <div>
                  {weightStatus?.status
                    ? tOr(`settings.garmin_weight_status.${weightStatus.status}`, weightStatus.status, {
                        weight: weightStatus.weight_kg == null ? '—' : formatCompact(weightStatus.weight_kg, lang),
                        date: weightStatus.date ? longDate(parseIsoDate(weightStatus.date), lang) : '—',
                      })
                    : t('settings.garmin_weight_status.empty')}
                </div>
                {weightStatus?.last_error ? (
                  <span className="set-note">
                    {t('settings.garmin_weight_last_error')}: {weightStatus.last_error}
                  </span>
                ) : null}
                {Boolean(weightStatus?.next_attempt_at) && (
                  <span className="set-note">
                    {t('settings.garmin_weight_next_attempt', { at: syncedLabel(String(weightStatus?.next_attempt_at), today, lang) })}
                  </span>
                )}
              </Alert>

              {weightExportEnabled ? (
                <div className="set-mt3">
                  <button
                    type="button"
                    className="ghost"
                    onClick={handleSendWeightNow}
                  >
                    <Icon name="upload" />
                    <span>{t('settings.garmin_weight_send_now')}</span>
                  </button>
                </div>
              ) : null}
            </div>

            <HealthImport />
          </div>
        </Section>

        {/* Claude.ai MCP Connector */}
        <Section title={t('settings.mcp_title')} className="set-sec">
          <p className="sub set-d">{t('settings.mcp_description')}</p>
          <div className="form">
            <label className="field">
              <span className="flabel">{t('settings.mcp_id')}</span>
              <input
                className="input"
                value={mcpClientId}
                onChange={(e) => setMcpClientId(e.target.value)}
              />
            </label>

            <label className="field">
              <span className="flabel split">
                <span>{t('settings.mcp_secret')}</span>
                <span className={`badge ${settings.mcp.mcp_client_secret_set ? 'good' : ''}`}>
                  {settings.mcp.mcp_client_secret_set ? t('settings.key_set') : t('settings.key_not_set')}
                </span>
              </span>
              <input
                type="password"
                className="input"
                placeholder={t('settings.mcp_secret_placeholder')}
                value={mcpClientSecret}
                onChange={(e) => setMcpClientSecret(e.target.value)}
              />
            </label>

            <div className="set-save">
              <button type="button" className="ghost" onClick={handleSaveMcp}>
                {t('settings.save_mcp')}
              </button>
            </div>
          </div>
        </Section>
      </div>
    </div>
  )
}
