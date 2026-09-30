import { useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { api, failText, InvalidError, ok, RequestError } from '@/api/client'
import { TextButton } from '@/components/controls/Marks'
import { Section } from '@/components/controls/Section'
import { toast } from '@/components/controls/toast'
import { Icon } from '@/components/icons/Icon'
import { useT } from '@/i18n/useT'
import { formatNumber } from '@/lib/format'

export type RestartPhase = 'idle' | 'confirm' | 'restarting'

/** First press asks "sure?", the second one fires the restart. While the app is coming
 *  back up the button does nothing. */
export function pressRestart(phase: RestartPhase): { phase: RestartPhase; fire: boolean } {
  if (phase === 'idle') return { phase: 'confirm', fire: false }
  if (phase === 'confirm') return { phase: 'restarting', fire: true }
  return { phase, fire: false }
}

export function DataSection() {
  const { t, lang } = useT()
  const queryClient = useQueryClient()
  const fileInputRef = useRef<HTMLInputElement>(null)

  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [isRestoring, setIsRestoring] = useState(false)
  const [restoreResult, setRestoreResult] = useState<string | null>(null)
  const [restartPhase, setRestartPhase] = useState<RestartPhase>('idle')

  // Download full backup
  const handleExportFull = async () => {
    try {
      toast(t('settings.export_started'))
      const res = await fetch('/api/v1/settings/export', { credentials: 'same-origin' })
      if (!res.ok) throw new RequestError(res.status)
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `vitals_backup_${new Date().toISOString().slice(0, 10)}.json`
      document.body.appendChild(a)
      a.click()
      a.remove()
      URL.revokeObjectURL(url)
    } catch (err) {
      toast(failText(err, t('app.action_failed')), { icon: 'warn' })
    }
  }

  // Download AI export
  const handleExportLlm = async () => {
    try {
      toast(t('settings.export_started'))
      const res = await fetch('/api/v1/settings/export-llm', { credentials: 'same-origin' })
      if (!res.ok) throw new RequestError(res.status)
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `vitals_llm_${new Date().toISOString().slice(0, 10)}.json`
      document.body.appendChild(a)
      a.click()
      a.remove()
      URL.revokeObjectURL(url)
    } catch (err) {
      toast(failText(err, t('app.action_failed')), { icon: 'warn' })
    }
  }

  // Handle file select
  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (file) {
      setSelectedFile(file)
      setRestoreResult(null)
    }
  }

  // Handle restore
  const handleRestore = async () => {
    if (!selectedFile) {
      fileInputRef.current?.click()
      return
    }

    if (!window.confirm(t('settings.import_confirm'))) {
      return
    }

    try {
      setIsRestoring(true)
      const body = new FormData()
      body.append('backup_file', selectedFile)

      const res = await fetch('/api/v1/settings/import', {
        method: 'POST',
        body,
        credentials: 'same-origin',
      })

      if (!res.ok) {
        // A refused backup says why in the user's language (`detail`); anything else is a plain failure.
        const errorData: { detail?: unknown } = await res.json().catch(() => ({}))
        throw typeof errorData.detail === 'string' && errorData.detail !== '' ? new InvalidError(errorData.detail) : new RequestError(res.status)
      }

      const data = await res.json()
      setRestoreResult(data.summary || t('settings.import_restored'))
      setSelectedFile(null)
      toast(t('settings.import_result_hint'))
      void queryClient.invalidateQueries()
    } catch (err) {
      toast(failText(err, t('app.action_failed')), { icon: 'warn' })
    } finally {
      setIsRestoring(false)
    }
  }

  // Container restart with 2-step confirmation
  const handleRestart = async () => {
    const step = pressRestart(restartPhase)
    setRestartPhase(step.phase)
    if (!step.fire) return
    try {
      await ok(api.POST('/api/v1/settings/restart'))
      toast(t('settings.saved.restart'))
    } catch (err) {
      setRestartPhase('idle')
      toast(failText(err, t('app.action_failed')), { icon: 'warn' })
    }
  }

  return (
    <Section title={t('settings.data_title')} className="set-sec narrow">
      <p className="sub set-d">{t('settings.data_description')}</p>

      <div className="form">
        {/* Export */}
        <div>
          <span className="flabel block">
            {t('settings.export_label')}
          </span>
          <div className="set-row-wrap">
            <button
              type="button"
              className="ghost"
              onClick={handleExportFull}
            >
              <Icon name="download" />
              <span>{t('settings.export_full')}</span>
            </button>
            <button
              type="button"
              className="ghost"
              onClick={handleExportLlm}
            >
              <Icon name="download" />
              <span>{t('settings.export_llm')}</span>
            </button>
          </div>
          <p className="fhint set-mt2">{t('settings.export_hint')}</p>
        </div>

        {/* Import */}
        <div className="set-sub-sec">
          <span className="flabel block">
            {t('settings.import_label')}
          </span>

          <div className="alert warn set-mb3">
            <Icon name="warn" />
            <div>{t('settings.import_warning')}</div>
          </div>

          <input
            ref={fileInputRef}
            type="file"
            accept=".json"
            hidden
            onChange={handleFileChange}
          />

          <button
            type="button"
            className="data-drop-btn"
            onClick={() => fileInputRef.current?.click()}
          >
            <span className="data-drop-icon">
              <Icon name="upload" />
            </span>
            <span>
              <b className="data-drop-name">
                {selectedFile ? selectedFile.name : t('settings.import_drop_text')}
              </b>
              <small className="data-drop-meta">
                {selectedFile
                  ? t('settings.file_size_kb', { size: formatNumber(selectedFile.size / 1024, lang, 1) })
                  : t('settings.import_drop_hint')}
              </small>
            </span>
          </button>

          <div className="set-mt3">
            <button
              type="button"
              className="ghost danger"
              onClick={handleRestore}
              disabled={isRestoring || !selectedFile}
            >
              <Icon name="sync" />
              <span>{isRestoring ? t('settings.import_restoring') : t('settings.import_submit')}</span>
            </button>
          </div>

          {restoreResult && (
            <div className="alert info set-mt3">
              <Icon name="check" />
              <div>
                <b>{restoreResult}</b>
                <p className="set-note">
                  {t('settings.import_result_hint')}
                </p>
              </div>
            </div>
          )}
        </div>

        {/* Container Restart */}
        <div className="set-sub-sec">
          <span className="flabel block">
            {t('settings.restart_title')}
          </span>
          <p className="fhint set-mb3">
            {restartPhase === 'restarting' ? t('settings.restart_text') : t('settings.restart_hint')}
          </p>
          <TextButton
            icon="sync"
            danger
            spinning={restartPhase === 'restarting'}
            disabled={restartPhase === 'restarting'}
            onClick={handleRestart}
          >
            {restartPhase === 'confirm' ? t('common.confirm_question') : t('settings.restart_btn')}
          </TextButton>
        </div>
      </div>
    </Section>
  )
}
