import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { api } from '@/api/client'
import { PrimaryButton } from '@/components/controls/PrimaryButton'
import { Section } from '@/components/controls/Section'
import { toast } from '@/components/controls/toast'
import { Icon } from '@/components/icons/Icon'
import { useT } from '@/i18n/useT'
import type { SettingsView } from './useSettingsView'

interface SecuritySectionProps {
  settings: SettingsView
}

export function SecuritySection({ settings }: SecuritySectionProps) {
  const { t } = useT()
  const queryClient = useQueryClient()

  // Password state
  const [oldPassword, setOldPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')

  // 2FA state: 'off' | 'setup' | 'on' | 'disable'
  const [tfaMode, setTfaMode] = useState<'off' | 'setup' | 'on' | 'disable'>(
    settings.security.twofa_enabled ? 'on' : 'off'
  )
  const [setupData, setSetupData] = useState<{ secret: string; otpauth_uri: string; qr_svg: string } | null>(null)
  const [code, setCode] = useState('')
  const [disableCode, setDisableCode] = useState('')

  // Change password
  const handleChangePassword = async () => {
    if (newPassword.length < 8) {
      toast(t('settings.error.password_too_short'), { icon: 'warn' })
      return false
    }
    if (newPassword !== confirmPassword) {
      toast(t('settings.error.password_mismatch'), { icon: 'warn' })
      return false
    }

    try {
      const res = await api.POST('/api/v1/settings/password', {
        body: {
          old_password: oldPassword,
          new_password: newPassword,
          new_password_confirm: confirmPassword,
        },
      })
      if (res.data) {
        toast(t('settings.saved.password'))
        setOldPassword('')
        setNewPassword('')
        setConfirmPassword('')
        return true
      }
      return false
    } catch (err: any) {
      toast(err.message || 'Error changing password', { icon: 'warn' })
      return false
    }
  }

  // Start 2FA setup
  const handleStartTfa = async () => {
    try {
      const res = await api.POST('/api/v1/settings/2fa/start')
      if (res.data) {
        setSetupData(res.data)
        setTfaMode('setup')
        setCode('')
      }
    } catch (err: any) {
      toast(err.message || 'Error starting 2FA setup', { icon: 'warn' })
    }
  }

  // Confirm 2FA setup
  const handleConfirmTfa = async () => {
    if (!code.trim()) return
    try {
      const res = await api.POST('/api/v1/settings/2fa/enable', {
        body: { code: code.trim() },
      })
      if (res.data) {
        toast(t('settings.saved.twofa'))
        setTfaMode('on')
        setSetupData(null)
        setCode('')
        void queryClient.invalidateQueries({ queryKey: ['settings'] })
      }
    } catch (err: any) {
      toast(err.message || t('settings.error.twofa_bad_code'), { icon: 'warn' })
    }
  }

  // Disable 2FA
  const handleDisableTfa = async () => {
    if (!disableCode.trim()) return
    try {
      const res = await api.POST('/api/v1/settings/2fa/disable', {
        body: { code: disableCode.trim() },
      })
      if (res.data) {
        toast(t('settings.saved.twofa_off'))
        setTfaMode('off')
        setDisableCode('')
        void queryClient.invalidateQueries({ queryKey: ['settings'] })
      }
    } catch (err: any) {
      toast(err.message || t('settings.error.twofa_bad_code'), { icon: 'warn' })
    }
  }

  // Copy secret key
  const handleCopyKey = () => {
    if (setupData?.secret) {
      void navigator.clipboard.writeText(setupData.secret)
      toast(t('settings.twofa_copied'))
    }
  }

  return (
    <div className="grid">
      <div className="c6">
        {/* Password Form */}
        <Section title={t('settings.password_label')} className="set-sec">
          <div className="form space-y-3">
            <label className="field">
              <span className="flabel">{t('settings.current_password')}</span>
              <input
                type="password"
                className="input"
                value={oldPassword}
                onChange={(e) => setOldPassword(e.target.value)}
              />
            </label>

            <label className="field">
              <span className="flabel">{t('settings.new_password')}</span>
              <input
                type="password"
                className="input"
                placeholder={t('settings.new_password_placeholder')}
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
              />
            </label>

            <label className="field">
              <span className="flabel">{t('settings.confirm_password')}</span>
              <input
                type="password"
                className="input"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
              />
            </label>

            <div className="set-save">
              <PrimaryButton onPress={handleChangePassword}>
                {t('settings.save_password')}
              </PrimaryButton>
            </div>
          </div>
        </Section>
      </div>

      <div className="c6">
        {/* 2FA Protection */}
        <Section title={t('settings.twofa_label')} className="set-sec">
          <p className="sub set-d">{t('settings.twofa_description')}</p>

          <div className="form">
            <div className="tfa" data-tfa={tfaMode}>
              {/* OFF */}
              {tfaMode === 'off' && (
                <div className="tfa-s flex items-center justify-between">
                  <div className="tfa-l">
                    <span className="badge">Выключена</span>
                  </div>
                  <button
                    type="button"
                    className="btn ghost flex items-center gap-2"
                    onClick={handleStartTfa}
                  >
                    <Icon name="lock" />
                    <span>{t('settings.twofa_enable')}</span>
                  </button>
                </div>
              )}

              {/* SETUP */}
              {tfaMode === 'setup' && setupData && (
                <div className="tfa-s space-y-4">
                  <div className="tfa-setup flex flex-col md:flex-row gap-4 items-start md:items-center">
                    <div
                      className="qr bg-white p-2 rounded-xl"
                      dangerouslySetInnerHTML={{ __html: setupData.qr_svg }}
                    />
                    <div className="tfa-key grow">
                      <span className="flabel text-xs text-[var(--muted)]">Ключ, если камера не нужна</span>
                      <div className="key font-mono text-sm tracking-wider my-2 p-2 bg-[var(--bg-2)] rounded border border-[var(--line)] select-all">
                        {setupData.secret}
                      </div>
                      <div className="flex gap-2">
                        <button
                          type="button"
                          className="btn ghost text-xs flex items-center gap-1.5"
                          onClick={handleCopyKey}
                        >
                          <Icon name="copy" />
                          <span>{t('settings.twofa_copy')}</span>
                        </button>
                        {setupData.otpauth_uri && (
                          <a
                            href={setupData.otpauth_uri}
                            className="btn ghost text-xs flex items-center gap-1.5"
                          >
                            <Icon name="link" />
                            <span>{t('settings.twofa_open_app')}</span>
                          </a>
                        )}
                      </div>
                    </div>
                  </div>

                  <label className="field">
                    <span className="flabel">{t('settings.twofa_code')}</span>
                    <input
                      type="text"
                      inputMode="numeric"
                      pattern="[0-9]*"
                      maxLength={6}
                      placeholder="000000"
                      className="input text-center tracking-widest text-lg w-40"
                      value={code}
                      onChange={(e) => setCode(e.target.value)}
                    />
                  </label>

                  <div className="flex gap-2">
                    <button
                      type="button"
                      className="btn ghost flex items-center gap-1.5"
                      onClick={handleConfirmTfa}
                    >
                      <Icon name="check" />
                      <span>{t('settings.twofa_confirm')}</span>
                    </button>
                    <button
                      type="button"
                      className="btn ghost"
                      onClick={() => {
                        setTfaMode('off')
                        setSetupData(null)
                        setCode('')
                      }}
                    >
                      {t('settings.twofa_cancel')}
                    </button>
                  </div>
                </div>
              )}

              {/* ON */}
              {tfaMode === 'on' && (
                <div className="tfa-s flex items-center justify-between">
                  <div className="tfa-l">
                    <span className="badge good">{t('settings.twofa_on')}</span>
                  </div>
                  <button
                    type="button"
                    className="btn ghost danger"
                    onClick={() => {
                      setTfaMode('disable')
                      setDisableCode('')
                    }}
                  >
                    {t('settings.twofa_disable')}
                  </button>
                </div>
              )}

              {/* DISABLE */}
              {tfaMode === 'disable' && (
                <div className="tfa-s space-y-3">
                  <label className="field">
                    <span className="flabel">Код из приложения, чтобы выключить</span>
                    <input
                      type="text"
                      inputMode="numeric"
                      pattern="[0-9]*"
                      maxLength={6}
                      placeholder="000000"
                      className="input text-center tracking-widest text-lg w-40"
                      value={disableCode}
                      onChange={(e) => setDisableCode(e.target.value)}
                    />
                  </label>

                  <div className="flex gap-2">
                    <button
                      type="button"
                      className="btn ghost danger"
                      onClick={handleDisableTfa}
                    >
                      {t('settings.twofa_disable')}
                    </button>
                    <button
                      type="button"
                      className="btn ghost"
                      onClick={() => {
                        setTfaMode('on')
                        setDisableCode('')
                      }}
                    >
                      {t('settings.twofa_cancel')}
                    </button>
                  </div>
                </div>
              )}
            </div>
          </div>
        </Section>
      </div>
    </div>
  )
}
