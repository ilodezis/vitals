import { useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
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
      toast(err.message || 'Error exporting full backup', { icon: 'warn' })
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
      toast(err.message || 'Error exporting LLM context', { icon: 'warn' })
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
      toast(err.message || 'Error restoring backup', { icon: 'warn' })
    } finally {
      setIsRestoring(false)
    }
  }

  return (
    <Section title={t('settings.data_title')} className="set-sec narrow">
      <p className="sub set-d">{t('settings.data_description')}</p>

      <div className="form space-y-4">
        {/* Export */}
        <div>
          <span className="flabel block mb-2">{t('settings.export_label')}</span>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              className="btn ghost flex items-center gap-2"
              onClick={handleExportFull}
            >
              <Icon name="download" />
              <span>{t('settings.export_full')}</span>
            </button>
            <button
              type="button"
              className="btn ghost flex items-center gap-2"
              onClick={handleExportLlm}
            >
              <Icon name="download" />
              <span>{t('settings.export_llm')}</span>
            </button>
          </div>
          <p className="fhint mt-2">{t('settings.export_hint')}</p>
        </div>

        {/* Import */}
        <div className="pt-4 border-t border-[var(--line)]">
          <span className="flabel block mb-2">{t('settings.import_label')}</span>

          <div className="alert warn flex items-start gap-2 mb-3">
            <Icon name="warn" />
            <div>{t('settings.import_warning')}</div>
          </div>

          <input
            ref={fileInputRef}
            type="file"
            accept=".json"
            className="hidden"
            onChange={handleFileChange}
          />

          <button
            type="button"
            className="drop w-full text-left p-4 rounded-xl border border-dashed border-[var(--line-strong)] hover:border-[var(--amber)] transition flex items-center gap-3"
            onClick={() => fileInputRef.current?.click()}
          >
            <span className="ico p-2 rounded-lg bg-[var(--bg-2)] text-[var(--fg)]">
              <Icon name="upload" />
            </span>
            <span>
              <b className="block text-sm text-[var(--fg)]">
                {selectedFile ? selectedFile.name : t('settings.import_drop_text')}
              </b>
              <small className="text-xs text-[var(--muted)]">
                {selectedFile
                  ? `${(selectedFile.size / 1024).toFixed(1)} KB`
                  : t('settings.import_drop_hint')}
              </small>
            </span>
          </button>

          <div className="mt-3">
            <button
              type="button"
              className="btn ghost danger flex items-center gap-2"
              onClick={handleRestore}
              disabled={isRestoring || !selectedFile}
            >
              <Icon name="sync" />
              <span>{isRestoring ? 'Восстановление…' : t('settings.import_submit')}</span>
            </button>
          </div>

          {restoreResult && (
            <div className="alert info mt-3 flex items-start gap-2">
              <Icon name="check" />
              <div>
                <b>{restoreResult}</b>
                <p className="text-xs text-[var(--muted)] mt-1">{t('settings.import_result_hint')}</p>
              </div>
            </div>
          )}
        </div>
      </div>
    </Section>
  )
}
