import { useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { failText, InvalidError, RequestError } from '@/api/client'
import type { components } from '@/api/schema'
import { toast } from '@/components/controls/toast'
import { Icon } from '@/components/icons/Icon'
import { useT } from '@/i18n/useT'
import { formatNumber } from '@/lib/format'

type ImportResult = components['schemas']['GarminImportResponse']

/** The fallback for days Garmin could not be read: a JSON export of the Health Auto Export
 *  app, uploaded by hand. It only fills in what the file has; what the watch already
 *  reported stays. */
export function HealthImport() {
  const { t, lang } = useT()
  const queryClient = useQueryClient()
  const input = useRef<HTMLInputElement>(null)
  const [file, setFile] = useState<File | null>(null)
  const [busy, setBusy] = useState(false)

  const upload = async () => {
    if (file === null) return
    setBusy(true)
    try {
      const body = new FormData()
      body.append('file', file)
      const res = await fetch('/api/v1/recovery/import', { method: 'POST', body, credentials: 'same-origin' })
      // A file that is not an export is refused with a 400; its reason is not in the user's language.
      if (res.status === 400) throw new InvalidError(t('app.recovery.import_invalid'))
      if (!res.ok) throw new RequestError(res.status)
      const result = (await res.json()) as ImportResult
      toast(t('garmin.sync_imported', { count: result.imported_days ?? 0 }))
      setFile(null)
      if (input.current !== null) input.current.value = ''
      void queryClient.invalidateQueries({ queryKey: ['recovery'] })
      void queryClient.invalidateQueries({ queryKey: ['today'] })
      // The rail's recovery row.
      void queryClient.invalidateQueries({ queryKey: ['session'] })
    } catch (err) {
      toast(failText(err, t('app.upload_failed')), { icon: 'warn' })
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="set-sub-sec">
      <span className="flabel block strong">{t('garmin.hae_title')}</span>
      <p className="fhint set-mb3">{t('garmin.hae_description')}</p>
      <input ref={input} type="file" accept="application/json,.json" hidden onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
      <button type="button" className="data-drop-btn" onClick={() => input.current?.click()}>
        <span className="data-drop-icon">
          <Icon name="upload" />
        </span>
        <span>
          <b className="data-drop-name">{file === null ? t('garmin.hae_drop_text') : file.name}</b>
          <small className="data-drop-meta">
            {file === null ? t('garmin.hae_drop_hint') : t('settings.file_size_kb', { size: formatNumber(file.size / 1024, lang, 1) })}
          </small>
        </span>
      </button>
      <div className="set-mt3">
        <button type="button" className="ghost" onClick={() => void upload()} disabled={file === null || busy}>
          <Icon name="upload" />
          <span>{busy ? t('app.recovery.importing') : t('garmin.hae_submit')}</span>
        </button>
      </div>
    </div>
  )
}
