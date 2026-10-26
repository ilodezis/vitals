import { useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { api, failText, ok } from '@/api/client'
import { useToday } from '@/app/session'
import { Section } from '@/components/controls/Section'
import { toast } from '@/components/controls/toast'
import { Icon } from '@/components/icons/Icon'
import { useT } from '@/i18n/useT'
import { shortDate, syncedLabel } from '@/lib/dates'
import { creationOptions, passkeysSupported, registrationJSON, signalAccepted } from './passkeys'
import type { SettingsView } from './useSettingsView'

interface PasskeysSectionProps {
  settings: SettingsView
}

/** The passkeys the owner signs in with: the list, adding one, removing one.
 *
 *  Adding is two taps on purpose. The first fetches the options while the owner names the key;
 *  the second opens the browser's sheet straight from the tap. Safari refuses a sheet that only
 *  arrives after a network round trip, so the fetch can't sit between the tap and the sheet. */
export function PasskeysSection({ settings }: PasskeysSectionProps) {
  const { t, lang } = useT()
  const today = useToday()
  const queryClient = useQueryClient()
  const security = settings.security
  const passkeys = security.passkeys ?? []

  // null: not adding. Otherwise the options for the sheet, once they have arrived.
  const [adding, setAdding] = useState<{ options: PublicKeyCredentialCreationOptions | null } | null>(null)
  const [creating, setCreating] = useState(false)
  const [name, setName] = useState('')
  const [confirming, setConfirming] = useState<number | null>(null)

  // Bumped by Cancel, so options that arrive afterwards don't reopen the form.
  const attempt = useRef(0)

  const refresh = () => queryClient.invalidateQueries({ queryKey: ['settings'] })

  const fetchOptions = async () => {
    const mine = ++attempt.current
    setAdding({ options: null })
    try {
      const json = await ok(api.POST('/api/v1/settings/passkeys/register/options'))
      if (mine === attempt.current) setAdding({ options: creationOptions(json) })
    } catch (err) {
      if (mine !== attempt.current) return
      setAdding(null)
      toast(failText(err, t('settings.error.passkey_failed')), { icon: 'warn' })
    }
  }

  const cancel = () => {
    attempt.current++
    setAdding(null)
    setName('')
  }

  const handleCreate = () => {
    const options = adding?.options
    if (!options || creating) return
    setCreating(true)
    // No await before this call: it has to run inside the tap.
    navigator.credentials
      .create({ publicKey: options })
      .then(async (credential) => {
        if (!(credential instanceof PublicKeyCredential)) throw new Error('no credential')
        await ok(api.POST('/api/v1/settings/passkeys/register/verify', {
          body: { credential: registrationJSON(credential), name: name.trim() },
        }))
        toast(t('settings.saved.passkey'))
        setAdding(null)
        setName('')
        void refresh()
      })
      .catch((err: unknown) => {
        // The challenge is spent either way: arm a fresh one for the next tap.
        void fetchOptions()
        const reason = err instanceof DOMException ? err.name : ''
        // NotAllowedError: the owner closed the sheet — nothing to report.
        if (reason === 'NotAllowedError') return
        if (reason === 'InvalidStateError') {
          toast(t('settings.error.passkey_already_registered'), { icon: 'warn' })
          return
        }
        toast(failText(err, t('settings.error.passkey_failed')), { icon: 'warn' })
      })
      .finally(() => setCreating(false))
  }

  const handleDelete = async (id: number) => {
    try {
      await ok(api.DELETE('/api/v1/settings/passkeys/{passkey_id}', {
        params: { path: { passkey_id: id } },
      }))
      toast(t('settings.saved.passkey_deleted'))
      setConfirming(null)
      if (security.passkey_rp_id && security.passkey_user_id) {
        signalAccepted(
          security.passkey_rp_id,
          security.passkey_user_id,
          passkeys.filter((p) => p.id !== id).map((p) => p.credential_id),
        )
      }
      void refresh()
    } catch (err) {
      toast(failText(err, t('app.save_failed')), { icon: 'warn' })
    }
  }

  return (
    <Section title={t('settings.passkeys_label')} className="set-sec">
      <p className="sub set-d">{t('settings.passkeys_description')}</p>

      {!security.passkeys_available ? (
        <p className="sub set-d">{t('settings.passkeys_unavailable')}</p>
      ) : (
        <div className="form">
          {passkeys.length === 0 ? (
            <p className="sub pk-empty">{t('settings.passkeys_empty')}</p>
          ) : (
            <ul className="pk-list">
              {passkeys.map((p) => (
                <li key={p.id} className="pk-row">
                  <div className="pk-l">
                    <span className="pk-name">
                      {p.name}
                      {p.backed_up && <span className="badge">{t('settings.passkey_synced')}</span>}
                    </span>
                    <span className="pk-meta">
                      {t('settings.passkey_added_on', { date: shortDate(new Date(p.created_at), lang) })}
                      {' · '}
                      {p.last_used_at
                        ? t('settings.passkey_last_used', { date: syncedLabel(p.last_used_at, today, lang) })
                        : t('settings.passkey_never_used')}
                    </span>
                  </div>
                  {confirming === p.id ? (
                    <div className="tfa-acts">
                      <button type="button" className="ghost danger" onClick={() => void handleDelete(p.id)}>
                        {t('settings.passkey_delete_confirm')}
                      </button>
                      <button type="button" className="ghost" onClick={() => setConfirming(null)}>
                        {t('common.cancel')}
                      </button>
                    </div>
                  ) : (
                    <button type="button" className="ghost" onClick={() => setConfirming(p.id)}>
                      <Icon name="trash" />
                      <span>{t('settings.passkey_delete')}</span>
                    </button>
                  )}
                </li>
              ))}
            </ul>
          )}

          {!passkeysSupported() ? (
            <p className="sub set-d">{t('settings.passkeys_unsupported')}</p>
          ) : adding === null ? (
            <div className="tfa-acts">
              <button type="button" className="ghost" onClick={() => void fetchOptions()}>
                <Icon name="plus" />
                <span>{t('settings.passkey_add')}</span>
              </button>
            </div>
          ) : (
            <div className="set-stack3">
              <label className="field">
                <span className="flabel">{t('settings.passkey_name')}</span>
                <input
                  type="text"
                  className="input"
                  maxLength={64}
                  placeholder={t('settings.passkey_name_placeholder')}
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                />
              </label>
              <div className="tfa-acts">
                <button
                  type="button"
                  className="ghost"
                  disabled={adding.options === null || creating}
                  aria-busy={adding.options === null || creating}
                  onClick={handleCreate}
                >
                  <Icon name="lock" />
                  <span>{t('settings.passkey_add')}</span>
                </button>
                <button type="button" className="ghost" onClick={cancel}>
                  {t('common.cancel')}
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </Section>
  )
}
