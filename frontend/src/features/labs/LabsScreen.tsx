import { useMemo, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { api, failText, InvalidError, ok } from '@/api/client'
import { MarkerChart } from '@/components/charts/MarkerChart'
import { FilterRow } from '@/components/controls/Choices'
import { Disclosure } from '@/components/controls/Disclosure'
import { ConflictAlert } from '@/components/controls/ConflictAlert'
import { RangeBar } from '@/components/controls/Meters'
import { Badge, Delta, TextButton } from '@/components/controls/Marks'
import { PrimaryButton, type PrimaryButtonHandle } from '@/components/controls/PrimaryButton'
import { FigureBody, Section } from '@/components/controls/Section'
import { toast } from '@/components/controls/toast'
import { Icon } from '@/components/icons/Icon'
import { useLayout } from '@/components/shell/layout'
import { DomainAlerts } from '@/components/controls/DomainAlerts'
import { Headline, Mast, TopBar } from '@/components/shell/PageHead'
import { useT } from '@/i18n/useT'
import { cx } from '@/lib/cx'
import { longDate, monthLong, parseIsoDate, shortDate, toIsoDate } from '@/lib/dates'
import { formatNumber } from '@/lib/format'
import { useConflictMutation } from '@/lib/useConflictMutation'
import { markerTrend, rangeText } from './notes'
import { statusOf, type LabMarker } from './types'
import { failureLine, hasSummary, uploadLabFile, type QueueTally } from './uploadQueue'
import { useLabsView } from './useLabsView'
import './labs.css'

/** The order the group filters come in. */
const GROUP_ORDER = ['metabolic', 'hormones', 'vitamins', 'lipids', 'thyroid']

/** Normalize group keys to unify variants like metabolism / metabolic. */
function normalizeGroupKey(k: string): string {
  const lower = k.toLowerCase().trim()
  if (lower === 'metabolism' || lower === '\u043C\u0435\u0442\u0430\u0431\u043E\u043B\u0438\u0437\u043C' || lower === 'metabolic') return 'metabolic'
  if (lower === 'hormones' || lower === '\u0433\u043E\u0440\u043C\u043E\u043D\u044B') return 'hormones'
  if (lower === 'vitamins' || lower === '\u0432\u0438\u0442\u0430\u043C\u0438\u043D\u044B') return 'vitamins'
  if (lower === 'lipids' || lower === '\u043B\u0438\u043F\u0438\u0434\u044B') return 'lipids'
  if (lower === 'thyroid' || lower === '\u0449\u0438\u0442\u043E\u0432\u0438\u0434\u043D\u0430\u044F') return 'thyroid'
  return lower
}

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
  const { t, tOr, lang } = useT()
  const view = useLabsView()
  const { desktop } = useLayout()
  const queryClient = useQueryClient()
  const fileInputRef = useRef<HTMLInputElement>(null)
  const confirmButtonRef = useRef<PrimaryButtonHandle>(null)
  const manualButtonRef = useRef<PrimaryButtonHandle>(null)

  const [filter, setFilter] = useState('all')
  const [filtered, setFiltered] = useState(false)
  const [selected, setSelected] = useState<string | null>(() => view.markers.find((m) => statusOf(m) !== 'ok')?.id ?? view.markers[0]?.id ?? null)

  // Upload & Extraction Preview state. Several files go one at a time: each is read, checked and
  // saved (or skipped) before the next one is sent.
  const [isUploading, setIsUploading] = useState(false)
  const [preview, setPreview] = useState<ExtractedPreview | null>(null)
  const queueRef = useRef<File[]>([])
  const tallyRef = useRef<QueueTally>({ added: 0, errors: [] })
  const [progress, setProgress] = useState<{ index: number; total: number; name: string; image: string | null } | null>(null)
  const [catalogOpen, setCatalogOpen] = useState(false)

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

  const releaseImage = () => setProgress((p) => {
    if (p?.image) URL.revokeObjectURL(p.image)
    return p === null ? null : { ...p, image: null }
  })

  // The queue is done: one line for what was added, one per file that failed.
  const finishQueue = () => {
    const tally = tallyRef.current
    if (hasSummary(tally)) {
      toast(t('app.labs.queue_added', { count: tally.added }), tally.errors.length > 0 ? { icon: 'warn' } : undefined)
      for (const line of tally.errors) toast(line, { icon: 'warn' })
    }
    tallyRef.current = { added: 0, errors: [] }
    queueRef.current = []
    releaseImage()
    setProgress(null)
  }

  // Send the next file; a failed one is noted and the queue moves past it.
  const advanceQueue = async () => {
    for (;;) {
      const file = queueRef.current.shift()
      if (file === undefined) {
        finishQueue()
        return
      }
      releaseImage()
      setProgress((p) => ({
        index: (p?.index ?? 0) + 1,
        total: p?.total ?? 1,
        name: file.name,
        image: file.type.startsWith('image/') ? URL.createObjectURL(file) : null,
      }))
      setIsUploading(true)
      const outcome = await uploadLabFile(file, t('app.upload_failed'))
      setIsUploading(false)
      if (outcome.kind === 'preview') {
        setPreview(outcome.lab)
        return
      }
      if (outcome.kind === 'stop' && tallyRef.current.added === 0 && tallyRef.current.errors.length === 0) {
        toast(outcome.reason, { icon: 'warn' })
        tallyRef.current = { added: 0, errors: [] }
        finishQueue()
        return
      }
      tallyRef.current.errors.push(failureLine(file.name, outcome.reason))
    }
  }

  const handleFileSelected = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? [])
    if (fileInputRef.current) fileInputRef.current.value = ''
    if (files.length === 0) return
    queueRef.current = files
    tallyRef.current = { added: 0, errors: [] }
    setProgress({ index: 0, total: files.length, name: '', image: null })
    void advanceQueue()
  }

  // This file's markers are not saved; the next file comes up.
  const skipPreview = () => {
    setPreview(null)
    confirmConflict.clearConflict()
    void advanceQueue()
  }

  // Closing the review stops the queue; what was saved stays saved.
  const stopQueue = () => {
    queueRef.current = []
    setPreview(null)
    confirmConflict.clearConflict()
    finishQueue()
  }

  // Confirm extracted markers
  const confirmConflict = useConflictMutation({
    mutationFn: async ({ override }) => {
      if (!preview) throw new InvalidError('')
      const saved = await ok(api.POST('/api/v1/labs/confirm', {
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
      }))
      tallyRef.current.added += saved.created
      setPreview(null)
      refresh()
      void advanceQueue()
    },
    fallbackErrorMessage: t('app.save_failed'),
    onError: (err) => {
      toast(failText(err, t('app.save_failed')), { icon: 'warn' })
    },
  })

  // Create manual result
  const manualConflict = useConflictMutation({
    mutationFn: async ({ override }) => {
      const value = Number.parseFloat(manVal)
      if (!manMarker.trim() || !Number.isFinite(value)) {
        throw new InvalidError(t('app.labs.manual_required'))
      }
      await ok(api.POST('/api/v1/labs/results', {
        body: {
          date: manDate,
          marker: manMarker.trim(),
          value,
          unit: manUnit.trim() || null,
          refLow: manRefLow ? parseFloat(manRefLow) : null,
          refHigh: manRefHigh ? parseFloat(manRefHigh) : null,
          labName: manLab.trim() || null,
          note: manNote.trim() || null,
          override,
        },
      }))
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
    fallbackErrorMessage: t('app.save_failed'),
    onError: (err) => {
      toast(failText(err, t('app.save_failed')), { icon: 'warn' })
    },
  })

  // Delete result
  const handleDeleteResult = async (resultId: string) => {
    try {
      await ok(api.DELETE('/api/v1/labs/results/{result_id}', {
        params: { path: { result_id: parseInt(resultId, 10) } },
      }))
      toast(t('common.deleted'))
      refresh()
    } catch (err) {
      toast(failText(err, t('app.delete_failed')), { icon: 'warn' })
    }
  }

  const out = view.markers.filter((m) => statusOf(m) !== 'ok')
  const groups = useMemo(() => {
    const seen = new Map<string, string>()
    for (const m of view.markers) {
      const normKey = normalizeGroupKey(m.groupKey)
      if (!seen.has(normKey)) {
        const translatedLabel = tOr(`app.lab_cat.${normKey}`, m.group)
        seen.set(normKey, translatedLabel)
      }
    }
    const rank = (key: string) => {
      const i = GROUP_ORDER.indexOf(key)
      return i === -1 ? GROUP_ORDER.length : i
    }
    return [...seen].sort(([a], [b]) => rank(a) - rank(b))
  }, [view.markers, tOr])

  const visible = view.markers.filter((m) => {
    if (filter === 'all') return true
    if (filter === 'out') return statusOf(m) !== 'ok'
    return normalizeGroupKey(m.groupKey) === filter
  })

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

  // With no result there is no collection date either: the server's stand-in (today) is not shown.
  const hasResults = view.markers.length > 0
  const sourceLabel = tOr(`app.source.${view.source}`, view.source)

  return (
    <>
      <input
        ref={fileInputRef}
        type="file"
        accept=".pdf,.png,.jpg,.jpeg"
        multiple
        style={{ display: 'none' }}
        onChange={handleFileSelected}
      />

      <TopBar title={t('nav.labs')} />
      <Mast
        screen="labs"
        actions={
          <div className="labs-acts">
            <TextButton icon="upload" onClick={() => fileInputRef.current?.click()} disabled={progress !== null}>
              {isUploading ? t('app.labs.parsing') : t('app.labs.upload_action')}
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
              sub={out.map((m) => m.name.replace(/\s*\(.*\)$/, '')).join(', ') || undefined}
              tone={out.length > 0 ? 'bad' : undefined}
              subBad={false}
            />
          </div>
          <div className="f">
            <FigureBody
              value={hasResults ? shortDate(collected, lang) : '—'}
              label={t('app.labs.fig_date')}
              sub={hasResults ? [view.lab, sourceLabel].filter((part) => part !== '').join(' · ') || undefined : undefined}
            />
          </div>
        </div>
      </Headline>
      <DomainAlerts domain="labs" />

      {/* Upload Drop Zone */}
      <button
        type="button"
        className="drop sec drop-first"
        onClick={() => fileInputRef.current?.click()}
        disabled={progress !== null}
      >
        <span className="ico">
          <Icon name="upload" />
        </span>
        <span>
          <b>{isUploading ? t('app.labs.extracting') : t('app.labs.drop_title')}</b>
          <small>
            {progress !== null && progress.total > 1 ? t('app.labs.queue_progress', { index: progress.index, total: progress.total }) : t('app.labs.drop_sub_many')}
          </small>
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
              const normKey = normalizeGroupKey(m.groupKey)
              const groupDisplay = tOr(`app.lab_cat.${normKey}`, m.group)
              return (
                <div
                  key={m.id}
                  className={cx('row', 'mk', open && 'sel', filtered && 'enter')}
                  style={filtered ? { animationDelay: `${i * 25}ms` } : undefined}
                  role="group"
                  aria-label={m.name}
                  onClick={() => pick(m.id)}
                >
                  {/* The row opens on a click anywhere; the name is its one real button, so the
                      delete button further down is a sibling and not a control inside a control. */}
                  <button type="button" className="mk-name" aria-expanded={desktop ? undefined : open}>
                    <span className="t">{m.name}</span>
                    <span className="m">{groupDisplay}</span>
                  </button>
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
                        <div className="mk-detail-acts">
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

      {view.catalog.length > 0 && (
        <Section className="lab-catalog">
          <Disclosure open={catalogOpen} onToggle={() => setCatalogOpen(!catalogOpen)} title={t('app.labs.catalog_title')} count={view.catalog.length}>
            <div className="rows">
              {view.catalog.map((c) => (
                <div key={c.name} className="row r-kv tight">
                  <span className="t plain">
                    {c.name}
                    {c.tier === 1 && (
                      <Badge tone="bad" className="lab-tier">
                        {t('app.labs.tier1')}
                      </Badge>
                    )}
                  </span>
                  <span className="m num">
                    {c.retestIntervalDays == null
                      ? '—'
                      : [
                          t('app.labs.retest_every', { days: c.retestIntervalDays }),
                          c.deferUntil ? t('app.labs.deferred_until', { date: shortDate(parseIsoDate(c.deferUntil), lang) }) : null,
                        ]
                          .filter((x) => x !== null)
                          .join(' · ')}
                  </span>
                </div>
              ))}
            </div>
          </Disclosure>
        </Section>
      )}

      {/* Modal: Extracted Markers Review & Confirm */}
      {preview && (
        <div className="hrt-form-modal">
          <div className="hrt-form-box" style={{ maxWidth: 640 }}>
            <div className="hrt-form-head">
              <div>
                <h3 className="lab-modal-title">{t('app.labs.preview_title')}</h3>
                <p className="lab-modal-sub">
                  {progress !== null && progress.total > 1 && <b className="num">{t('app.labs.queue_progress', { index: progress.index, total: progress.total })} · </b>}
                  {progress?.name ? `${progress.name} · ` : ''}
                  {t('app.labs.preview_sub')}
                </p>
              </div>
              <button type="button" className="ibtn" aria-label={t('app.close')} onClick={stopQueue}>
                <Icon name="x" />
              </button>
            </div>
            {progress?.image && <img className="lab-file-thumb" src={progress.image} alt={progress.name} />}
            <div className="lab-modal-form">
              <div className="lab-modal-grid2">
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
                  <span className="flabel">{t('app.labs.clinic_label')}</span>
                  <input
                    className="input"
                    value={preview.labName || ''}
                    placeholder={t('app.labs.clinic_ph')}
                    onChange={(e) => setPreview({ ...preview, labName: e.target.value })}
                  />
                </label>
              </div>

              <div className="preview-table-wrap">
                <table className="preview-table">
                  <thead>
                    <tr>
                      <th>{t('app.labs.marker_label')}</th>
                      <th>{t('app.labs.value_label')}</th>
                      <th>{t('app.labs.unit_label')}</th>
                      <th>{t('app.labs.range')}</th>
                      <th className="cell-action"></th>
                    </tr>
                  </thead>
                  <tbody>
                    {preview.markers.map((m, idx) => (
                      <tr key={idx}>
                        <td>
                          <input
                            className="input input-compact"
                            value={m.marker || ''}
                            onChange={(e) => {
                              const updated = [...preview.markers]
                              updated[idx] = { ...updated[idx], marker: e.target.value }
                              setPreview({ ...preview, markers: updated })
                            }}
                          />
                        </td>
                        <td className="cell-sm">
                          <input
                            type="number"
                            step="any"
                            className="input input-compact"
                            value={m.value ?? ''}
                            onChange={(e) => {
                              const updated = [...preview.markers]
                              updated[idx] = { ...updated[idx], value: parseFloat(e.target.value) || null }
                              setPreview({ ...preview, markers: updated })
                            }}
                          />
                        </td>
                        <td className="cell-sm">
                          <input
                            className="input input-compact"
                            value={m.unit || ''}
                            onChange={(e) => {
                              const updated = [...preview.markers]
                              updated[idx] = { ...updated[idx], unit: e.target.value }
                              setPreview({ ...preview, markers: updated })
                            }}
                          />
                        </td>
                        <td className="cell-range">
                          <div className="preview-range-box">
                            <input
                              type="number"
                              step="any"
                              placeholder={t('app.labs.ref_min_ph')}
                              className="input input-compact"
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
                              placeholder={t('app.labs.ref_max_ph')}
                              className="input input-compact"
                              value={m.refHigh ?? ''}
                              onChange={(e) => {
                                const updated = [...preview.markers]
                                updated[idx] = { ...updated[idx], refHigh: parseFloat(e.target.value) || null }
                                setPreview({ ...preview, markers: updated })
                              }}
                            />
                          </div>
                        </td>
                        <td className="cell-action">
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
              <div className="lab-modal-foot">
                <TextButton
                  icon="plus"
                  onClick={() => {
                    setPreview({
                      ...preview,
                      markers: [...preview.markers, { marker: '', value: 0, unit: '', refLow: null, refHigh: null }],
                    })
                  }}
                >
                  {t('app.labs.add_row')}
                </TextButton>
                <div className="lab-modal-foot-acts">
                  {progress !== null && progress.index < progress.total ? (
                    <TextButton onClick={skipPreview}>{t('app.labs.skip')}</TextButton>
                  ) : (
                    <TextButton onClick={skipPreview}>{t('common.cancel')}</TextButton>
                  )}
                  <PrimaryButton ref={confirmButtonRef} onPress={confirmConflict.submit}>
                    {t('app.labs.save_markers_count', { count: preview.markers.length })}
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
              <h3 className="lab-modal-title">{t('app.labs.manual_title')}</h3>
              <button type="button" className="ibtn" onClick={() => setManualOpen(false)}>
                <Icon name="x" />
              </button>
            </div>
            <div className="lab-modal-form">
              <label className="field">
                <span className="flabel">{t('common.date')}</span>
                <input type="date" className="input" value={manDate} onChange={(e) => setManDate(e.target.value)} />
              </label>
              <label className="field">
                <span className="flabel">{t('app.labs.marker_label')}</span>
                <input className="input" placeholder={t('app.labs.marker_ph')} value={manMarker} onChange={(e) => setManMarker(e.target.value)} />
              </label>
              <div className="lab-modal-grid2">
                <label className="field">
                  <span className="flabel">{t('app.labs.value_label')}</span>
                  <input type="number" step="any" className="input" value={manVal} onChange={(e) => setManVal(e.target.value)} />
                </label>
                <label className="field">
                  <span className="flabel">{t('app.labs.unit_label')}</span>
                  <input className="input" placeholder={t('app.labs.unit_ph')} value={manUnit} onChange={(e) => setManUnit(e.target.value)} />
                </label>
              </div>
              <div className="lab-modal-grid2">
                <label className="field">
                  <span className="flabel">{t('app.labs.ref_low')}</span>
                  <input type="number" step="any" className="input" value={manRefLow} onChange={(e) => setManRefLow(e.target.value)} />
                </label>
                <label className="field">
                  <span className="flabel">{t('app.labs.ref_high')}</span>
                  <input type="number" step="any" className="input" value={manRefHigh} onChange={(e) => setManRefHigh(e.target.value)} />
                </label>
              </div>
              <label className="field">
                <span className="flabel">{t('app.labs.clinic_label')}</span>
                <input className="input" placeholder={t('app.labs.clinic_ph')} value={manLab} onChange={(e) => setManLab(e.target.value)} />
              </label>
              <label className="field">
                <span className="flabel">{t('app.labs.note_label')}</span>
                <input className="input" placeholder={t('app.labs.note_ph')} value={manNote} onChange={(e) => setManNote(e.target.value)} />
              </label>
              <ConflictAlert
                violations={manualConflict.violations}
                onFix={() => manualConflict.clearConflict()}
                onSaveAnyway={() => manualButtonRef.current?.press({ override: true })}
              />
              <PrimaryButton ref={manualButtonRef} className="btn grow" onPress={manualConflict.submit}>
                {t('common.save')}
              </PrimaryButton>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
