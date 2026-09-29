import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { api } from '@/api/client'
import { PrimaryButton } from '@/components/controls/PrimaryButton'
import { Section } from '@/components/controls/Section'
import { toast } from '@/components/controls/toast'
import { Icon } from '@/components/icons/Icon'
import { useT } from '@/i18n/useT'
import type { SettingsView } from './useSettingsView'

interface ConnectionsSectionProps {
  settings: SettingsView
}

export function ConnectionsSection({ settings }: ConnectionsSectionProps) {
  const { t } = useT()
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
      const res = await api.POST('/api/v1/settings/ai', {
        body: {
          openrouter_api_key: apiKey.trim() || undefined,
          openrouter_base_url: baseUrl.trim() || undefined,
          llm_model_digest: digestModel.trim() || undefined,
          llm_model_parser: parserModel.trim() || undefined,
          llm_model_brief: briefModel.trim() || undefined,
        },
      })
      if (res.data) {
        toast(t('settings.saved.ai'))
        setApiKey('')
        void queryClient.invalidateQueries({ queryKey: ['settings'] })
        return true
      }
      return false
    } catch (err: any) {
      toast(err.message || 'Error saving AI settings', { icon: 'warn' })
      return false
    }
  }

  // Save Hevy
  const handleSaveHevy = async () => {
    try {
      const res = await api.POST('/api/v1/settings/hevy', {
        body: {
          hevy_api_key: hevyKey.trim() || undefined,
        },
      })
      if (res.data) {
        toast(t('settings.saved.hevy'))
        setHevyKey('')
        void queryClient.invalidateQueries({ queryKey: ['settings'] })
        return true
      }
      return false
    } catch (err: any) {
      toast(err.message || 'Error saving Hevy settings', { icon: 'warn' })
      return false
    }
  }

  // Save Garmin credentials
  const handleSaveGarmin = async () => {
    try {
      const res = await api.POST('/api/v1/settings/garmin', {
        body: {
          garmin_email: garminEmail.trim() || undefined,
          garmin_password: garminPassword.trim() || undefined,
        },
      })
      if (res.data) {
        toast(t('settings.saved.garmin'))
        setGarminPassword('')
        void queryClient.invalidateQueries({ queryKey: ['settings'] })
        return true
      }
      return false
    } catch (err: any) {
      toast(err.message || 'Error saving Garmin credentials', { icon: 'warn' })
      return false
    }
  }

  // Toggle Garmin weight export
  const handleToggleWeightExport = async () => {
    const next = !weightExportEnabled
    try {
      const res = await api.POST('/api/v1/settings/garmin/weight-toggle', {
        body: { enabled: next },
      })
      if (res.data) {
        setWeightExportEnabled(next)
        toast(
          next
            ? t('settings.garmin_weight_action.toggle_enabled')
            : t('settings.garmin_weight_action.toggle_disabled')
        )
        void queryClient.invalidateQueries({ queryKey: ['settings'] })
      }
    } catch (err: any) {
      toast(err.message || 'Error toggling weight export', { icon: 'warn' })
    }
  }

  // Send weight now
  const handleSendWeightNow = async () => {
    try {
      const res = await api.POST('/api/v1/settings/garmin/weight/send-now')
      if (res.data) {
        toast(t('settings.garmin_weight_action.sent'))
        void queryClient.invalidateQueries({ queryKey: ['settings'] })
      }
    } catch (err: any) {
      toast(err.message || 'Error sending weight to Garmin', { icon: 'warn' })
    }
  }

  // Save MCP
  const handleSaveMcp = async () => {
    try {
      const res = await api.POST('/api/v1/settings/mcp', {
        body: {
          mcp_client_id: mcpClientId.trim() || undefined,
          mcp_client_secret: mcpClientSecret.trim() || undefined,
        },
      })
      if (res.data) {
        toast(t('settings.saved.mcp'))
        setMcpClientSecret('')
        void queryClient.invalidateQueries({ queryKey: ['settings'] })
        return true
      }
      return false
    } catch (err: any) {
      toast(err.message || 'Error saving MCP settings', { icon: 'warn' })
      return false
    }
  }

  const weightStatus = settings.garmin.garmin_weight_status as Record<string, any> | null

  return (
    <div className="grid">
      <div className="c6">
        {/* OpenRouter AI */}
        <Section title={t('settings.ai_title')} className="set-sec">
          <p className="sub set-d">{t('settings.ai_description')}</p>
          <div className="form space-y-3">
            <label className="field">
              <span className="flabel" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
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
                placeholder="пусто = модель дайджеста"
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
              <PrimaryButton onPress={handleSaveAi}>
                {t('settings.save_ai')}
              </PrimaryButton>
            </div>
          </div>
        </Section>

        {/* Hevy */}
        <Section title={t('settings.hevy_title')} className="set-sec">
          <p className="sub set-d">{t('settings.hevy_description')}</p>
          <div className="form space-y-3">
            <label className="field">
              <span className="flabel" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
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
              <PrimaryButton onPress={handleSaveHevy}>
                {t('settings.save_hevy')}
              </PrimaryButton>
            </div>
          </div>
        </Section>
      </div>

      <div className="c6">
        {/* Garmin Connect */}
        <Section title={t('settings.garmin_title')} className="set-sec">
          <p className="sub set-d">{t('settings.garmin_description')}</p>
          <div className="form space-y-3">
            <div className="grid grid-cols-2 gap-2">
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
                <span className="flabel" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
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
              <PrimaryButton onPress={handleSaveGarmin}>
                {t('settings.save_garmin')}
              </PrimaryButton>
            </div>

            {/* Garmin Weight Export */}
            <div className="sub-sec pt-4 border-t border-[var(--line)]">
              <span className="flabel font-semibold block mb-2">{t('settings.garmin_weight_export_label')}</span>
              <button
                type="button"
                className={`opt ${weightExportEnabled ? 'on' : ''}`}
                onClick={handleToggleWeightExport}
              >
                {weightExportEnabled ? 'Включено' : 'Выключено'}
              </button>
              <p className="fhint mt-2">{t('settings.garmin_weight_export_hint')}</p>

              {weightStatus && weightStatus.status && (
                <div className="alert info mt-3 flex items-start gap-2">
                  <Icon name="check" />
                  <div>
                    <div>{String(weightStatus.message || `Garmin: ${weightStatus.status}`)}</div>
                    {Boolean(weightStatus.next_attempt) && (
                      <span className="text-xs text-[var(--muted)] block mt-1">
                        {t('settings.garmin_weight_next_attempt', { at: String(weightStatus.next_attempt) })}
                      </span>
                    )}
                  </div>
                </div>
              )}

              <div className="mt-3">
                <button
                  type="button"
                  className="btn ghost flex items-center gap-2"
                  onClick={handleSendWeightNow}
                >
                  <Icon name="upload" />
                  <span>{t('settings.garmin_weight_send_now')}</span>
                </button>
              </div>
            </div>
          </div>
        </Section>

        {/* Claude.ai MCP Connector */}
        <Section title={t('settings.mcp_title')} className="set-sec">
          <p className="sub set-d">{t('settings.mcp_description')}</p>
          <div className="form space-y-3">
            <label className="field">
              <span className="flabel">{t('settings.mcp_id')}</span>
              <input
                className="input"
                value={mcpClientId}
                onChange={(e) => setMcpClientId(e.target.value)}
              />
            </label>

            <label className="field">
              <span className="flabel" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
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
              <PrimaryButton onPress={handleSaveMcp}>
                {t('settings.save_mcp')}
              </PrimaryButton>
            </div>
          </div>
        </Section>
      </div>
    </div>
  )
}
