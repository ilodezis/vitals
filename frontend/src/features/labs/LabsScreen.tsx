import { useMemo, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { api } from '@/api/client'
import { MarkerChart } from '@/components/charts/MarkerChart'
import { FilterRow } from '@/components/controls/Choices'
import { ConflictAlert } from '@/components/controls/ConflictAlert'
import { RangeBar } from '@/components/controls/Meters'
import { Delta, TextButton } from '@/components/controls/Marks'
import { PrimaryButton, type PrimaryButtonHandle } from '@/components/controls/PrimaryButton'
import { FigureBody } from '@/components/controls/Section'
import { toast } from '@/components/controls/toast'
import { Icon } from '@/components/icons/Icon'
import { useLayout } from '@/components/shell/layout'
import { Headline, Mast, TopBar } from '@/components/shell/PageHead'
import { useT } from '@/i18n/useT'
import { cx } from '@/lib/cx'
import { longDate, monthLong, parseIsoDate, shortDate, toIsoDate } from '@/lib/dates'
import { formatNumber } from '@/lib/format'
import { useConflictMutation } from '@/lib/useConflictMutation'
import { markerTrend, rangeText } from './notes'
import { statusOf, type LabMarker } from './types'
import { useLabsView } from './useLabsView'
import './labs.css'

const lowerFirst = (text: string): string => text.charAt(0).toLowerCase() + text.slice(1)

/** The order the group filters come in. */
const GROUP_ORDER = ['metabolism', 'hormones', 'vitamins']

/** A stretch of the scale that reads better than the whole range for markers whose reference range
 *  is very wide next to where the results sit. The server will send this with the marker. */
const FOCUS: Record<string, readonly [number, number]> = { vitd: [10, 60], tg: [60, 190], fer: [20, 160] }

interface ExtractedMarkerRow {
  marker?: string | null
  value?: number | null
  unit?: string | null
  refLow?: number | null
  refHigh?: number | null
}

interface ExtractedPreview {
  date: string
  labName?: string | null
  fileKey?: string | null
  rawPayloadId?: number | null
  markers: ExtractedMarkerRow[]
}

export default function LabsScreen() {
  const { t, lang } = useT()
  const view = useLabsView()
  const { desktop } = useLayout()
  const queryClient = useQueryClient()
  const fileInputRef = useRef<HTMLInputElement>(null)
  const confirmButtonRef = useRef<PrimaryButtonHandle>(null)
  const manualButtonRef = useRef<PrimaryButtonHandle>(null)

  const [filter, setFilter] = useState('all')
  const [filtered, setFiltered] = useState(false)
  const [selected, setSelected] = useState<string | null>(() => view.markers.find((m) => statusOf(m) !== 'ok')?.id ?? view.markers[0]?.id ?? null)

  // Upload & Extraction Preview state
  const [isUploading, setIsUploading] = useState(false)
  const [preview, setPreview] = useState<ExtractedPreview | null>(null)

  // Manual entry modal state
  const [manualOpen, setManualOpen] = useState(false)
  const todayStr = useMemo(() => toIsoDate(new Date()), [])
  const [manDate, setManDate] = useState(todayStr)
  const [manMarker, setManMarker] = useState('')
  const [manVal, setManVal] = useState('')
  const [manUnit, setManUnit] = useState('')
  const [manRefLow, setManRefLow] = useState('')
  const [manRefHigh, setManRefHigh] = useState('')
  const [manLab, setManLab] = useState('')
  const [manNote, setManNote] = useState('')

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ['labs'] })
    void queryClient.invalidateQueries({ queryKey: ['today'] })
  }

  // Upload handler
  const handleFileSelected = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    setIsUploading(true)
    try {
      const fd = new FormData()
      fd.append('file', file)
      const res = await fetch('/api/v1/labs/upload', {
        method: 'POST',
        body: fd,
        credentials: 'same-origin',
      })
      if (!res.ok) throw new Error('Lab report upload failed')
      const data = await res.json()
      if (!data.ok) {
        toast(data.message || 'Could not parse document', { icon: 'warn' })
      } else if (data.lab) {
        setPreview(data.lab)
        toast('Document parsed — review extracted markers below', { icon: 'pulse' })
      }
    } catch (err: any) {
      toast(err.message || 'Upload error', { icon: 'warn' })
    } finally {
      setIsUploading(false)
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

  // Confirm extracted markers
  const confirmConflict = useConflictMutation({
    mutationFn: async ({ override }) => {
      if (!preview) throw new Error('No preview')
      await api.POST('/api/v1/labs/confirm', {
        body: {
          date: preview.date,
          labName: preview.labName || null,
          fileKey: preview.fileKey || null,
          rawPayloadId: preview.rawPayloadId || null,
          markers: preview.markers.map((m) => ({
            marker: m.marker || undefined,
            value: m.value ?? undefined,
            unit: m.unit || undefined,
            refLow: m.refLow ?? undefined,
            refHigh: m.refHigh ?? undefined,
          })),
          override,
        },
      })
      toast('Biomarkers saved successfully')
      setPreview(null)
      refresh()
    },
    onError: (err) => {
      toast(err.message || 'Error confirming markers', { icon: 'warn' })
    },
  })

  // Create manual result
  const manualConflict = useConflictMutation({
    mutationFn: async ({ override }) => {
      if (!manMarker.trim() || !manVal) {
        throw new Error('Marker name and value are required')
      }
      await api.POST('/api/v1/labs/results', {
        body: {
          date: manDate,
          marker: manMarker.trim(),
          value: parseFloat(manVal) || 0,
          unit: manUnit.trim() || null,
          refLow: manRefLow ? parseFloat(manRefLow) : null,
          refHigh: manRefHigh ? parseFloat(manRefHigh) : null,
          labName: manLab.trim() || null,
          note: manNote.trim() || null,
          override,
        },
      })
      toast(t('common.saved'))
      setManualOpen(false)
      setManMarker('')
      setManVal('')
      setManUnit('')
      setManRefLow('')
      setManRefHigh('')
      setManLab('')
      setManNote('')
      refresh()
    },
    onError: (err) => {
      toast(err.message || 'Error saving marker', { icon: 'warn' })
    },
  })

  // Delete result
  const handleDeleteResult = async (resultId: string) => {
    try {
      await api.DELETE('/api/v1/labs/results/{result_id}', {
        params: { path: { result_id: parseInt(resultId, 10) } },
      })
      toast(t('common.deleted'))
      refresh()
    } catch (err: any) {
      toast(err.message || 'Error deleting result', { icon: 'warn' })
    }
  }

  const out = view.markers.filter((m) => statusOf(m) !== 'ok')
  const groups = useMemo(() => {
    const seen = new Map<string, string>()
    for (const m of view.markers) if (!seen.has(m.groupKey)) seen.set(m.groupKey, m.group)
    const rank = (key: string) => {
      const i = GROUP_ORDER.indexOf(key)
      return i === -1 ? GROUP_ORDER.length : i
    }
    return [...seen].sort(([a], [b]) => rank(a) - rank(b))
  }, [view.markers])

  const visible = view.markers.filter((m) => (filter === 'all' ? true : filter === 'out' ? statusOf(m) !== 'ok' : m.groupKey === filter))
  const shown = view.markers.find((m) => m.id === selected) ?? view.markers[0]
  const num = (m: LabMarker, v: number) => formatNumber(v, lang, m.decimals)
  const collected = parseIsoDate(view.collectedIso)

  const pick = (id: string) => setSelected((prev) => (desktop ? id : prev === id ? null : id))
  const statusText = (m: LabMarker) => t(`app.labs.status.${statusOf(m)}`)
  const noteFor = (m: LabMarker) => {
    const trend = markerTrend(m)
    const since = monthLong(parseIsoDate(m.history[0]?.dateIso ?? view.collectedIso), lang)
    const start = t(trend.direction === 'up' ? 'app.labs.note.up' : 'app.labs.note.down', { date: since, from: num(m, trend.first), to: num(m, trend.last), unit: m.unit })
    const low = trend.status === 'low'
    const verdict =
      trend.status === 'ok'
        ? t('app.labs.note.ok')
        : trend.improving
          ? t(low ? 'app.labs.note.improving_low' : 'app.labs.note.improving_high')
          : t(low ? 'app.labs.note.worsening_low' : 'app.labs.note.worsening_high')
    return `${start} ${verdict}`
  }
  const historyOf = (m: LabMarker) => m.history.map((h) => ({ date: parseIsoDate(h.dateIso), value: h.value }))

  return (
    <>
      <input
        ref={fileInputRef}
        type="file"
        accept=".pdf,.png,.jpg,.jpeg"
        style={{ display: 'none' }}
        onChange={handleFileSelected}
      />

      <TopBar title={t('nav.labs')} />
      <Mast
        screen="labs"
        actions={
          <div className="flex gap-2">
            <TextButton icon="upload" onClick={() => fileInputRef.current?.click()} disabled={isUploading}>
              {isUploading ? 'Parsing...' : t('app.labs.upload_action')}
            </TextButton>
            <TextButton icon="plus" onClick={() => setManualOpen(true)}>
              {t('common.add')}
            </TextButton>
          </div>
        }
      />
      <Headline title={t('nav.labs')}>
        <div className="figs inline n3">
          <div className="f">
            <FigureBody value={view.markers.length} label={t('app.labs.fig_markers')} sub={t('app.labs.fig_markers_sub')} />
          </div>
          <div className="f">
            <FigureBody
              value={out.length}
              label={t('app.labs.fig_out')}
              sub={out.map((m) => lowerFirst(m.name.replace(/\s*\(.*\)$/, ''))).join(', ') || undefined}
              tone={out.length > 0 ? 'bad' : undefined}
              subBad={false}
            />
          </div>
          <div className="f">
            <FigureBody value={shortDate(collected, lang)} label={t('app.labs.fig_date')} sub={`${view.lab} · ${view.source}`} />
          </div>
        </div>
      </Headline>

      {/* Upload Drop Zone */}
      <button
        type="button"
        className="drop sec drop-first"
        onClick={() => fileInputRef.current?.click()}
        disabled={isUploading}
      >
        <span className="ico">
          <Icon name="upload" />
        </span>
        <span>
          <b>{isUploading ? 'Uploading and extracting biomarkers...' : t('app.labs.drop_title')}</b>
          <small>{t('app.labs.drop_sub')}</small>
        </span>
      </button>

      <FilterRow
        value={filter}
        onChange={(id) => {
          setFilter(id)
          setFiltered(true)
        }}
        options={[
          { id: 'all', label: `${t('app.labs.filter_all')} ${view.markers.length}` },
          { id: 'out', label: t('app.labs.filter_out'), count: out.length },
          ...groups.map(([id, label]) => ({ id, label })),
        ]}
      />

      <div className="grid labs-grid">
        <div className="c7">
          <div className="rows mk-list">
            {visible.map((m, i) => {
              const status = statusOf(m)
              const bad = status !== 'ok'
              const open = selected === m.id
              return (
                <div
                  key={m.id}
                  className={cx('row', 'mk', open && 'sel', filtered && 'enter')}
                  style={filtered ? { animationDelay: `${i * 25}ms` } : undefined}
                  role="button"
                  tabIndex={0}
                  aria-expanded={desktop ? undefined : open}
                  onClick={() => pick(m.id)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault()
                      pick(m.id)
                    }
                  }}
                >
                  <div>
                    <div className="t">{m.name}</div>
                    <div className="m">{m.group}</div>
                  </div>
                  <div className="mk-value">
                    <div className={cx('v', bad && 'bad')}>
                      {num(m, m.value)}
                      <span className="u">{m.unit}</span>
                    </div>
                    <div className={cx('st', bad ? 'bad' : 'fine')}>{statusText(m)}</div>
                  </div>
                  <RangeBar value={m.value} lo={m.lo} hi={m.hi} min={m.min} max={m.max} tone={bad ? 'bad' : ''} />
                  <div className="scale">
                    <span>{num(m, m.min)}</span>
                    <span>{t('app.labs.norm', { range: rangeText(m, (v, d) => formatNumber(v, lang, d)) })}</span>
                    <span>{num(m, m.max)}</span>
                  </div>
                  <div className={cx('mk-detail', 'collapse', open && 'open')}>
                    <div>
                      <div className="mk-detail-in">
                        {open && !desktop && (
                          <MarkerChart lo={m.lo} hi={m.hi} min={m.min} max={m.max} decimals={m.decimals} history={historyOf(m)} focus={FOCUS[m.id]} />
                        )}
                        <p className="mk-note">{noteFor(m)}</p>
                        <div className="mt-2 text-right">
                          <button
                            type="button"
                            className="ibtn danger"
                            onClick={(e) => {
                              e.stopPropagation()
                              void handleDeleteResult(m.id)
                            }}
                            aria-label={t('common.delete')}
                          >
                            <Icon name="x" />
                          </button>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        </div>

        <div className="c5">
          <div className="lab-side sticky">
            {shown !== undefined && (
              <div className="panel" key={shown.id}>
                <div className="panel-h">
                  <h3>{shown.name}</h3>
                  <span className="sub">{longDate(collected, lang)}</span>
                </div>
                <div className="fig-hero lab-hero">
                  <div className={cx('big', statusOf(shown) !== 'ok' && 'bad')}>
                    {num(shown, shown.value)}
                    <span className="unit">{shown.unit}</span>
                  </div>
                  <div className="side">
                    <Delta tone={statusOf(shown) !== 'ok' ? 'bad' : undefined}>{statusText(shown)}</Delta>
                    <span className="sub">{t('app.labs.norm', { range: rangeText(shown, (v, d) => formatNumber(v, lang, d)) })}</span>
                  </div>
                </div>
                {desktop && (
                  <div className="lab-chart">
                    <MarkerChart lo={shown.lo} hi={shown.hi} min={shown.min} max={shown.max} decimals={shown.decimals} history={historyOf(shown)} focus={FOCUS[shown.id]} />
                  </div>
                )}
                <p className="mk-note">{noteFor(shown)}</p>
                <div className="rows lab-history">
                  {[...shown.history].reverse().map((h) => {
                    const out = h.value < shown.lo || h.value > shown.hi
                    return (
                      <div key={h.dateIso} className="row r-kv lab-past">
                        <span className="m">{longDate(parseIsoDate(h.dateIso), lang)}</span>
                        <div className={cx('v', out && 'bad')}>
                          {num(shown, h.value)}
                          <span className="u">{shown.unit}</span>
                        </div>
                      </div>
                    )
                  })}
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Modal: Extracted Markers Review & Confirm */}
      {preview && (
        <div className="hrt-form-modal">
          <div className="hrt-form-box" style={{ maxWidth: 640 }}>
            <div className="hrt-form-head">
              <div>
                <h3 className="font-bold text-lg">Review Extracted Biomarkers</h3>
                <p className="text-xs text-[var(--muted)]">Verify or correct the parsed values before saving to your records.</p>
              </div>
              <button type="button" className="ibtn" onClick={() => setPreview(null)}>
                <Icon name="x" />
              </button>
            </div>
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-3">
                <label className="field">
                  <span className="flabel">{t('common.date')}</span>
                  <input
                    type="date"
                    className="input"
                    value={preview.date}
                    onChange={(e) => setPreview({ ...preview, date: e.target.value })}
                  />
                </label>
                <label className="field">
                  <span className="flabel">Lab / Clinic</span>
                  <input
                    className="input"
                    value={preview.labName || ''}
                    placeholder="e.g. Invitro, Synevo"
                    onChange={(e) => setPreview({ ...preview, labName: e.target.value })}
                  />
                </label>
              </div>

              <div className="border border-[var(--line)] rounded-xl overflow-hidden">
                <table className="w-full text-xs text-left">
                  <thead className="bg-[var(--bg-deep)] text-[var(--muted)]">
                    <tr>
                      <th className="p-2">Marker</th>
                      <th className="p-2">Value</th>
                      <th className="p-2">Unit</th>
                      <th className="p-2">Ref Range</th>
                      <th className="p-2"></th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[var(--line)]">
                    {preview.markers.map((m, idx) => (
                      <tr key={idx}>
                        <td className="p-2">
                          <input
                            className="input text-xs py-1"
                            value={m.marker || ''}
                            onChange={(e) => {
                              const updated = [...preview.markers]
                              updated[idx] = { ...updated[idx], marker: e.target.value }
                              setPreview({ ...preview, markers: updated })
                            }}
                          />
                        </td>
                        <td className="p-2 w-20">
                          <input
                            type="number"
                            step="any"
                            className="input text-xs py-1"
                            value={m.value ?? ''}
                            onChange={(e) => {
                              const updated = [...preview.markers]
                              updated[idx] = { ...updated[idx], value: parseFloat(e.target.value) || null }
                              setPreview({ ...preview, markers: updated })
                            }}
                          />
                        </td>
                        <td className="p-2 w-20">
                          <input
                            className="input text-xs py-1"
                            value={m.unit || ''}
                            onChange={(e) => {
                              const updated = [...preview.markers]
                              updated[idx] = { ...updated[idx], unit: e.target.value }
                              setPreview({ ...preview, markers: updated })
                            }}
                          />
                        </td>
                        <td className="p-2 w-28">
                          <div className="flex gap-1 items-center">
                            <input
                              type="number"
                              step="any"
                              placeholder="min"
                              className="input text-xs py-1"
                              value={m.refLow ?? ''}
                              onChange={(e) => {
                                const updated = [...preview.markers]
                                updated[idx] = { ...updated[idx], refLow: parseFloat(e.target.value) || null }
                                setPreview({ ...preview, markers: updated })
                              }}
                            />
                            <span>–</span>
                            <input
                              type="number"
                              step="any"
                              placeholder="max"
                              className="input text-xs py-1"
                              value={m.refHigh ?? ''}
                              onChange={(e) => {
                                const updated = [...preview.markers]
                                updated[idx] = { ...updated[idx], refHigh: parseFloat(e.target.value) || null }
                                setPreview({ ...preview, markers: updated })
                              }}
                            />
                          </div>
                        </td>
                        <td className="p-2 text-center">
                          <button
                            type="button"
                            className="ibtn danger"
                            onClick={() => {
                              setPreview({
                                ...preview,
                                markers: preview.markers.filter((_, i) => i !== idx),
                              })
                            }}
                          >
                            <Icon name="x" />
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <ConflictAlert
                violations={confirmConflict.violations}
                onFix={() => confirmConflict.clearConflict()}
                onSaveAnyway={() => confirmButtonRef.current?.press({ override: true })}
              />
              <div className="flex justify-between items-center pt-2">
                <TextButton
                  icon="plus"
                  onClick={() => {
                    setPreview({
                      ...preview,
                      markers: [...preview.markers, { marker: '', value: 0, unit: '', refLow: null, refHigh: null }],
                    })
                  }}
                >
                  Add Row
                </TextButton>
                <div className="flex gap-2">
                  <TextButton onClick={() => setPreview(null)}>Cancel</TextButton>
                  <PrimaryButton ref={confirmButtonRef} onPress={confirmConflict.submit}>
                    Save {preview.markers.length} Markers
                  </PrimaryButton>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Modal: Manual Marker Entry */}
      {manualOpen && (
        <div className="hrt-form-modal">
          <div className="hrt-form-box">
            <div className="hrt-form-head">
              <h3 className="font-bold text-lg">Record Biomarker</h3>
              <button type="button" className="ibtn" onClick={() => setManualOpen(false)}>
                <Icon name="x" />
              </button>
            </div>
            <div className="space-y-3">
              <label className="field">
                <span className="flabel">{t('common.date')}</span>
                <input type="date" className="input" value={manDate} onChange={(e) => setManDate(e.target.value)} />
              </label>
              <label className="field">
                <span className="flabel">Biomarker *</span>
                <input className="input" placeholder="e.g. Ferritin, TSH, Total Testosterone" value={manMarker} onChange={(e) => setManMarker(e.target.value)} />
              </label>
              <div className="grid grid-cols-2 gap-2">
                <label className="field">
                  <span className="flabel">Value *</span>
                  <input type="number" step="any" className="input" value={manVal} onChange={(e) => setManVal(e.target.value)} />
                </label>
                <label className="field">
                  <span className="flabel">Unit</span>
                  <input className="input" placeholder="e.g. ng/mL, mIU/L" value={manUnit} onChange={(e) => setManUnit(e.target.value)} />
                </label>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <label className="field">
                  <span className="flabel">Ref Low</span>
                  <input type="number" step="any" className="input" value={manRefLow} onChange={(e) => setManRefLow(e.target.value)} />
                </label>
                <label className="field">
                  <span className="flabel">Ref High</span>
                  <input type="number" step="any" className="input" value={manRefHigh} onChange={(e) => setManRefHigh(e.target.value)} />
                </label>
              </div>
              <label className="field">
                <span className="flabel">Lab / Clinic</span>
                <input className="input" placeholder="e.g. Invitro" value={manLab} onChange={(e) => setManLab(e.target.value)} />
              </label>
              <label className="field">
                <span className="flabel">Note</span>
                <input className="input" placeholder="e.g. Fasting, morning draw" value={manNote} onChange={(e) => setManNote(e.target.value)} />
              </label>
              <ConflictAlert
                violations={manualConflict.violations}
                onFix={() => manualConflict.clearConflict()}
                onSaveAnyway={() => manualButtonRef.current?.press({ override: true })}
              />
              <PrimaryButton ref={manualButtonRef} className="w mt-4" onPress={manualConflict.submit}>
                {t('common.save')}
              </PrimaryButton>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
