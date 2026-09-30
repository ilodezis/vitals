import { useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { api } from '@/api/client'
import { TextButton } from '@/components/controls/Marks'
import { Section } from '@/components/controls/Section'
import { toast } from '@/components/controls/toast'
import { Icon } from '@/components/icons/Icon'
import { useT } from '@/i18n/useT'

export function DataSection() {
  const { t } = useT()
  const queryClient = useQueryClient()
  const fileInputRef = useRef<HTMLInputElement>(null)

  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [isRestoring, setIsRestoring] = useState(false)
  const [restoreResult, setRestoreResult] = useState<string | null>(null)
  const [confirmRestart, setConfirmRestart] = useState(false)

  // Download full backup
  const handleExportFull = async () => {
    try {
      toast(t('settings.export_started'))
      const res = await fetch('/api/v1/settings/export/full', { credentials: 'same-origin' })
      if (!res.ok) throw new Error(`Export failed with status ${res.status}`)
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `vitals_backup_${new Date().toISOString().slice(0, 10)}.json`
      document.body.appendChild(a)
      a.click()
      a.remove()
      URL.revokeObjectURL(url)
    } catch (err: any) {
      toast(err.message || t('app.error'), { icon: 'warn' })
    }
  }

  // Download AI export
  const handleExportLlm = async () => {
    try {
      toast(t('settings.export_started'))
      const res = await fetch('/api/v1/settings/export/llm', { credentials: 'same-origin' })
      if (!res.ok) throw new Error(`Export failed with status ${res.status}`)
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `vitals_llm_${new Date().toISOString().slice(0, 10)}.json`
      document.body.appendChild(a)
      a.click()
      a.remove()
      URL.revokeObjectURL(url)
    } catch (err: any) {
      toast(err.message || t('app.error'), { icon: 'warn' })
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
        const errorData = await res.json().catch(() => ({}))
        throw new Error(errorData.detail || errorData.message || `Import failed with status ${res.status}`)
      }

      const data = await res.json()
      setRestoreResult(data.summary || 'Restored successfully')
      setSelectedFile(null)
      toast(t('settings.import_result_hint'))
      void queryClient.invalidateQueries()
    } catch (err: any) {
      toast(err.message || t('app.error'), { icon: 'warn' })
    } finally {
      setIsRestoring(false)
    }
  }

  // Container restart with 2-step confirmation
  const handleRestart = async () => {
    if (!confirmRestart) {
      setConfirmRestart(true)
      return
    }
    setConfirmRestart(false)
    try {
      const res = await api.POST('/api/v1/settings/restart')
      if (res.data) {
        toast(t('settings.saved.restart'))
      }
    } catch (err: any) {
      toast(err.message || t('app.error'), { icon: 'warn' })
    }
  }

  return (
    <Section title={t('settings.data_title')} className="set-sec narrow">
      <p className="sub set-d">{t('settings.data_description')}</p>

      <div className="form">
        {/* Export */}
        <div>
          <span className="flabel" style={{ display: 'block', marginBottom: '8px' }}>
            {t('settings.export_label')}
          </span>
          <div className="set-row-wrap">
            <button
              type="button"
              className="btn ghost"
              style={{ display: 'inline-flex', alignItems: 'center', gap: '8px' }}
              onClick={handleExportFull}
            >
              <Icon name="download" />
              <span>{t('settings.export_full')}</span>
            </button>
            <button
              type="button"
              className="btn ghost"
              style={{ display: 'inline-flex', alignItems: 'center', gap: '8px' }}
              onClick={handleExportLlm}
            >
              <Icon name="download" />
              <span>{t('settings.export_llm')}</span>
            </button>
          </div>
          <p className="fhint" style={{ marginTop: '8px' }}>{t('settings.export_hint')}</p>
        </div>

        {/* Import */}
        <div className="set-sub-sec">
          <span className="flabel" style={{ display: 'block', marginBottom: '8px' }}>
            {t('settings.import_label')}
          </span>

          <div className="alert warn" style={{ display: 'flex', alignItems: 'flex-start', gap: '8px', marginBottom: '12px' }}>
            <Icon name="warn" />
            <div>{t('settings.import_warning')}</div>
          </div>

          <input
            ref={fileInputRef}
            type="file"
            accept=".json"
            style={{ display: 'none' }}
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
              <b style={{ display: 'block', fontSize: 'var(--t-body)' }}>
                {selectedFile ? selectedFile.name : t('settings.import_drop_text')}
              </b>
              <small style={{ fontSize: 'var(--t-caption)', color: 'var(--muted)' }}>
                {selectedFile
                  ? `${(selectedFile.size / 1024).toFixed(1)} KB`
                  : t('settings.import_drop_hint')}
              </small>
            </span>
          </button>

          <div style={{ marginTop: '12px' }}>
            <button
              type="button"
              className="btn ghost"
              style={{ display: 'inline-flex', alignItems: 'center', gap: '8px', color: 'var(--bad)' }}
              onClick={handleRestore}
              disabled={isRestoring || !selectedFile}
            >
              <Icon name="sync" />
              <span>{isRestoring ? t('settings.import_restoring') : t('settings.import_submit')}</span>
            </button>
          </div>

          {restoreResult && (
            <div className="alert info" style={{ marginTop: '12px', display: 'flex', alignItems: 'flex-start', gap: '8px' }}>
              <Icon name="check" />
              <div>
                <b>{restoreResult}</b>
                <p style={{ fontSize: 'var(--t-micro)', color: 'var(--muted)', marginTop: '4px' }}>
                  {t('settings.import_result_hint')}
                </p>
              </div>
            </div>
          )}
        </div>

        {/* Container Restart */}
        <div className="set-sub-sec">
          <span className="flabel" style={{ display: 'block', marginBottom: '8px' }}>
            {t('settings.restart_title')}
          </span>
          <p className="fhint" style={{ marginBottom: '12px' }}>
            {t('settings.restart_text')}
          </p>
          <TextButton
            icon="sync"
            danger
            onClick={handleRestart}
          >
            {confirmRestart ? t('common.confirm_question') : t('settings.restart_btn')}
          </TextButton>
        </div>
      </div>
    </Section>
  )
}
