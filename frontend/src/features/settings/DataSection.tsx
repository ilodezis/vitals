import { type FormEvent, useId, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { api, failText, InvalidError, ok, RequestError } from '@/api/client'
import { useTodayIso } from '@/app/session'
import { Alert } from '@/components/controls/Alert'
import { OptionGroup } from '@/components/controls/Choices'
import { DateField } from '@/components/controls/DateField'
import { TextButton } from '@/components/controls/Marks'
import { Section } from '@/components/controls/Section'
import { toast } from '@/components/controls/toast'
import { Icon } from '@/components/icons/Icon'
import { useT } from '@/i18n/useT'
import { addDays, parseIsoDate, shortDate, toIsoDate } from '@/lib/dates'
import { formatNumber, type Lang } from '@/lib/format'
import { HealthImport } from './HealthImport'

export type RestartPhase = 'idle' | 'confirm' | 'restarting'

/** First press asks "sure?", the second one fires the restart. While the app is coming
 *  back up the button does nothing. */
export function pressRestart(phase: RestartPhase): { phase: RestartPhase; fire: boolean } {
  if (phase === 'idle') return { phase: 'confirm', fire: false }
  if (phase === 'confirm') return { phase: 'restarting', fire: true }
  return { phase, fire: false }
}

export type LlmPeriod = '7' | '30' | '90' | '365' | 'all' | 'custom'

export const LLM_PERIOD_PRESETS: readonly LlmPeriod[] = ['7', '30', '90', '365', 'all', 'custom']

export interface LlmExportRange {
  since?: string
  until?: string
}

export type LlmRangeError = 'need_date' | 'bad_period'

export type LlmRangeResult =
  | { ok: true; range: LlmExportRange }
  | { ok: false; error: LlmRangeError }

/** Resolve the selected LLM export period into inclusive ISO bounds, or a validation error code
 *  when a custom range is empty or inverted. */
export function resolveLlmExportRange(
  period: LlmPeriod,
  todayIso: string,
  customStart: string,
  customEnd: string,
): LlmRangeResult {
  if (period === 'all') return { ok: true, range: {} }
  if (period === 'custom') {
    const since = customStart.trim() || undefined
    const until = customEnd.trim() || undefined
    if (since === undefined && until === undefined) {
      return { ok: false, error: 'need_date' }
    }
    if (since !== undefined && until !== undefined && until < since) {
      return { ok: false, error: 'bad_period' }
    }
    return {
      ok: true,
      range: {
        ...(since !== undefined && { since }),
        ...(until !== undefined && { until }),
      },
    }
  }
  const days = Number(period)
  const since = toIsoDate(addDays(parseIsoDate(todayIso), -(days - 1)))
  return { ok: true, range: { since, until: todayIso } }
}

/** Build the `/api/v1/settings/export-llm` request URL for a resolved range. */
export function buildLlmExportUrl(range: LlmExportRange): string {
  const params = new URLSearchParams()
  if (range.since) params.set('since', range.since)
  if (range.until) params.set('until', range.until)
  const qs = params.toString()
  return qs === '' ? '/api/v1/settings/export-llm' : `/api/v1/settings/export-llm?${qs}`
}

/** Fallback download filename when Content-Disposition is unavailable. */
export function llmExportFilename(range: LlmExportRange, todayIso: string): string {
  if (range.since && range.until) return `vitals_llm_${range.since}_${range.until}.json`
  if (range.since) return `vitals_llm_from_${range.since}.json`
  if (range.until) return `vitals_llm_until_${range.until}.json`
  return `vitals_llm_${todayIso}.json`
}

function filenameFromDisposition(header: string | null): string | null {
  if (header === null) return null
  const match = /filename="([^"]+)"/i.exec(header)
  return match?.[1] ?? null
}

function formatSpanEdge(iso: string, todayYear: number, lang: Lang): string {
  const d = parseIsoDate(iso)
  const label = shortDate(d, lang)
  return d.getFullYear() === todayYear ? label : `${label} ${d.getFullYear()}`
}

function defaultCustomStart(todayIso: string): string {
  return toIsoDate(addDays(parseIsoDate(todayIso), -29))
}

export function DataSection() {
  const { t, lang } = useT()
  const todayIso = useTodayIso()
  const queryClient = useQueryClient()
  const fileInputRef = useRef<HTMLInputElement>(null)
  const fromInputRef = useRef<HTMLInputElement>(null)
  const toInputRef = useRef<HTMLInputElement>(null)

  const formHeadingId = useId()
  const fromId = useId()
  const toId = useId()
  const errorId = useId()

  const [llmPeriod, setLlmPeriod] = useState<LlmPeriod>('90')
  const [customStart, setCustomStart] = useState('')
  const [customEnd, setCustomEnd] = useState('')
  const [rangeError, setRangeError] = useState<LlmRangeError | null>(null)
  const [isExportingLlm, setIsExportingLlm] = useState(false)
  const [isExportingFull, setIsExportingFull] = useState(false)

  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [isRestoring, setIsRestoring] = useState(false)
  const [restoreResult, setRestoreResult] = useState<string | null>(null)
  const [restartPhase, setRestartPhase] = useState<RestartPhase>('idle')

  const handlePeriodChange = (next: string) => {
    const period = next as LlmPeriod
    setLlmPeriod(period)
    setRangeError(null)
    if (period === 'custom' && customStart === '' && customEnd === '') {
      setCustomStart(defaultCustomStart(todayIso))
      setCustomEnd(todayIso)
    }
  }

  const handleCustomStartChange = (iso: string) => {
    setCustomStart(iso)
    if (rangeError !== null) setRangeError(null)
  }

  const handleCustomEndChange = (iso: string) => {
    setCustomEnd(iso)
    if (rangeError !== null) setRangeError(null)
  }

  const validateCustomOnBlur = () => {
    if (llmPeriod !== 'custom') return
    const check = resolveLlmExportRange('custom', todayIso, customStart, customEnd)
    setRangeError(check.ok ? null : check.error)
  }

  const presetRangeHint = (() => {
    if (llmPeriod === 'all' || llmPeriod === 'custom') return null
    const resolved = resolveLlmExportRange(llmPeriod, todayIso, '', '')
    if (!resolved.ok || !resolved.range.since || !resolved.range.until) return null
    const todayYear = parseIsoDate(todayIso).getFullYear()
    return `${formatSpanEdge(resolved.range.since, todayYear, lang)} — ${formatSpanEdge(resolved.range.until, todayYear, lang)}`
  })()

  // Download full backup
  const handleExportFull = async () => {
    setIsExportingFull(true)
    try {
      toast(t('settings.export_started'))
      const res = await fetch('/api/v1/settings/export', { credentials: 'same-origin' })
      if (!res.ok) throw new RequestError(res.status)
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = filenameFromDisposition(res.headers.get('content-disposition')) ?? `vitals_backup_${todayIso}.json`
      document.body.appendChild(a)
      a.click()
      a.remove()
      URL.revokeObjectURL(url)
    } catch (err) {
      toast(failText(err, t('app.action_failed')), { icon: 'warn' })
    } finally {
      setIsExportingFull(false)
    }
  }

  // Download AI export for the selected period
  const handleExportLlm = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    const resolved = resolveLlmExportRange(llmPeriod, todayIso, customStart, customEnd)
    if (!resolved.ok) {
      setRangeError(resolved.error)
      const target = resolved.error === 'bad_period' ? toInputRef.current : fromInputRef.current
      target?.focus()
      return
    }

    setRangeError(null)
    setIsExportingLlm(true)
    try {
      toast(t('settings.export_started'))
      const res = await fetch(buildLlmExportUrl(resolved.range), { credentials: 'same-origin' })
      if (!res.ok) {
        const errData: { message?: unknown; detail?: unknown } = await res.json().catch(() => ({}))
        const msg =
          typeof errData.message === 'string' && errData.message !== ''
            ? errData.message
            : typeof errData.detail === 'string' && errData.detail !== ''
              ? errData.detail
              : null
        throw msg !== null ? new InvalidError(msg) : new RequestError(res.status)
      }
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download =
        filenameFromDisposition(res.headers.get('content-disposition')) ??
        llmExportFilename(resolved.range, todayIso)
      document.body.appendChild(a)
      a.click()
      a.remove()
      URL.revokeObjectURL(url)
    } catch (err) {
      toast(failText(err, t('app.action_failed')), { icon: 'warn' })
    } finally {
      setIsExportingLlm(false)
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

  // Out, then in, then what replaces or stops everything — the dangerous end of the tab.
  return (
    <>
      <Section title={t('settings.export_label')} className="set-sec">
        <form
          className="form"
          action="/api/v1/settings/export-llm"
          method="get"
          aria-labelledby={formHeadingId}
          onSubmit={handleExportLlm}
          noValidate
        >
          <span id={formHeadingId} className="flabel block strong">
            {t('settings.export_llm_title')}
          </span>
          <p className="sub set-d">{t('settings.export_llm_hint')}</p>

          <div className="field">
            <span className="flabel">{t('settings.export_llm_period')}</span>
            <OptionGroup
              label={t('settings.export_llm_period')}
              value={llmPeriod}
              onChange={handlePeriodChange}
              options={LLM_PERIOD_PRESETS.map((id) => ({
                id,
                label:
                  id === 'all'
                    ? t('settings.export_llm_period_all')
                    : id === 'custom'
                      ? t('settings.export_llm_period_custom')
                      : t('settings.export_llm_period_days', { n: id }),
              }))}
            />
            {presetRangeHint !== null && <p className="fhint num">{presetRangeHint}</p>}
          </div>

          {llmPeriod === 'custom' && (
            <div className="set-grid-2 set-mt3">
              <div className="field">
                <label className="flabel" htmlFor={fromId}>
                  {t('settings.export_llm_from')}
                </label>
                <DateField
                  id={fromId}
                  name="since"
                  value={customStart}
                  max={todayIso}
                  placeholder="—"
                  invalid={rangeError !== null}
                  describedBy={rangeError !== null ? errorId : undefined}
                  inputRef={fromInputRef}
                  onChange={handleCustomStartChange}
                  onBlur={validateCustomOnBlur}
                />
              </div>
              <div className="field">
                <label className="flabel" htmlFor={toId}>
                  {t('settings.export_llm_to')}
                </label>
                <DateField
                  id={toId}
                  name="until"
                  value={customEnd}
                  max={todayIso}
                  placeholder="—"
                  invalid={rangeError === 'bad_period'}
                  describedBy={rangeError !== null ? errorId : undefined}
                  inputRef={toInputRef}
                  onChange={handleCustomEndChange}
                  onBlur={validateCustomOnBlur}
                />
              </div>
            </div>
          )}

          {rangeError !== null && (
            <Alert tone="warn" className="set-mt3">
              <span id={errorId} role="alert">
                {t(rangeError === 'bad_period' ? 'settings.export_llm_bad_period' : 'settings.export_llm_need_date')}
              </span>
            </Alert>
          )}

          <div className="set-mt3">
            <button type="submit" className="ghost" disabled={isExportingLlm}>
              <Icon name="download" />
              <span>{t('settings.export_llm')}</span>
            </button>
          </div>
        </form>

        <div className="set-sub-sec">
          <span className="flabel block strong">{t('settings.export_full_title')}</span>
          <p className="sub set-d">{t('settings.export_full_hint')}</p>
          <button type="button" className="ghost" onClick={handleExportFull} disabled={isExportingFull}>
            <Icon name="download" />
            <span>{t('settings.export_full')}</span>
          </button>
        </div>
      </Section>

      <HealthImport />

      <Section title={t('settings.restore_title')} className="set-sec">
        <Alert tone="warn" className="set-mb3">
          {t('settings.import_warning')}
        </Alert>

        <input ref={fileInputRef} type="file" accept=".json" hidden onChange={handleFileChange} />

        <button type="button" className="data-drop-btn" onClick={() => fileInputRef.current?.click()}>
          <span className="data-drop-icon">
            <Icon name="upload" />
          </span>
          <span>
            <b className="data-drop-name">{selectedFile ? selectedFile.name : t('settings.import_drop_text')}</b>
            <small className="data-drop-meta">
              {selectedFile ? t('settings.file_size_kb', { size: formatNumber(selectedFile.size / 1024, lang, 1) }) : t('settings.import_drop_hint')}
            </small>
          </span>
        </button>

        <div className="set-mt3">
          <button type="button" className="ghost danger" onClick={handleRestore} disabled={isRestoring || !selectedFile}>
            <Icon name="sync" />
            <span>{isRestoring ? t('settings.import_restoring') : t('settings.import_submit')}</span>
          </button>
        </div>

        {restoreResult && (
          <Alert tone="info" icon="check" className="set-mt3">
            <b>{restoreResult}</b>
            <span className="set-note">{t('settings.import_result_hint')}</span>
          </Alert>
        )}
      </Section>

      <Section title={t('settings.restart_title')} className="set-sec">
        <p className="sub set-d">{restartPhase === 'restarting' ? t('settings.restart_text') : t('settings.restart_hint')}</p>
        <TextButton
          icon="sync"
          danger
          spinning={restartPhase === 'restarting'}
          disabled={restartPhase === 'restarting'}
          onClick={handleRestart}
        >
          {restartPhase === 'confirm' ? t('common.confirm_question') : t('settings.restart_btn')}
        </TextButton>
      </Section>
    </>
  )
}
