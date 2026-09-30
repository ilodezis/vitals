import { useMemo, useRef, useState } from 'react'
import { useMutation, useQueryClient, useSuspenseQuery } from '@tanstack/react-query'
import { api, failText, InvalidError, ok, RequestError } from '@/api/client'
import { useTodayIso } from '@/app/session'
import { ConfirmButton } from '@/components/controls/ConfirmButton'
import { ConflictAlert } from '@/components/controls/ConflictAlert'
import { Disclosure } from '@/components/controls/Disclosure'
import { DomainAlerts } from '@/components/controls/DomainAlerts'
import { Delta } from '@/components/controls/Marks'
import { Odometer } from '@/components/controls/Odometer'
import { Segmented } from '@/components/controls/Segmented'
import { Section } from '@/components/controls/Section'
import { Icon } from '@/components/icons/Icon'
import { Headline, TopBar } from '@/components/shell/PageHead'
import { toast } from '@/components/controls/toast'
import { useT } from '@/i18n/useT'
import { longDate, parseIsoDate, shortDate } from '@/lib/dates'
import { formatCompact, formatNumber, formatPercent } from '@/lib/format'
import { useConflictMutation } from '@/lib/useConflictMutation'
import { computeNavyFatPct } from './navy'
import { readScanMetrics, toScanPreview, type ScanPreviewMetric } from './scanMetrics'
import { buildMeasureBody } from './weightEdit'
import type { components } from '@/api/schema'
import './weight.css'

type WeightMeasuresView = components['schemas']['WeightMeasuresView']
type BodyScanUploadResponse = components['schemas']['BodyScanUploadResponse']
type Measurement = components['schemas']['BodyMeasurementItem']

export const measuresQuery = {
  queryKey: ['weight', 'measures'],
  queryFn: async (): Promise<WeightMeasuresView> => {
    const { data, error } = await api.GET('/api/v1/weight/measures')
    if (error !== undefined || data === undefined) throw new Error('Measures could not be read')
    return data
  },
}

export default function WeightMeasuresScreen() {
  const { t, lang, plural } = useT()
  const queryClient = useQueryClient()
  const view = useSuspenseQuery(measuresQuery).data
  const metricsCount = (n: number) => plural(n, t('app.weight.metrics.one', { n }), t('app.weight.metrics.few', { n }), t('app.weight.metrics.many', { n }))

  const [activePane, setActivePane] = useState<'measure' | 'noise' | 'photo' | 'body'>('measure')
  const [openScanId, setOpenScanId] = useState<number | null>(null)

  // Measure form state
  const todayStr = useTodayIso()
  const [mDate, setMDate] = useState(todayStr)
  const [neckCm, setNeckCm] = useState('')
  const [waistCm, setWaistCm] = useState('')
  const [hipsCm, setHipsCm] = useState('')
  const [mNote, setMNote] = useState('')
  // The tape measurement the form is correcting; `null` while it is adding a new one.
  const [editingMeasure, setEditingMeasure] = useState<{ id: number; date: string } | null>(null)
  const measureForm = useRef<HTMLFormElement>(null)

  // Noise form state
  const [nStart, setNStart] = useState(todayStr)
  const [nEnd, setNEnd] = useState('')
  const [nReason, setNReason] = useState('')
  const [nDirection, setNDirection] = useState<'n' | 'u' | 'd'>('n')

  // Photo form state
  const [phDate, setPhDate] = useState(todayStr)
  const [phNote, setPhNote] = useState('')
  const [phFiles, setPhFiles] = useState<FileList | null>(null)

  // BIA scan upload state
  const [scanFile, setScanFile] = useState<File | null>(null)
  const [previewMetrics, setPreviewMetrics] = useState<ScanPreviewMetric[]>([])
  const [previewDate, setPreviewDate] = useState(todayStr)
  const [previewDevice, setPreviewDevice] = useState('')
  const [previewFileKey, setPreviewFileKey] = useState('')
  const [previewRawId, setPreviewRawId] = useState<number | null>(null)
  const [isScanning, setIsScanning] = useState(false)

  // Calculated Navy Fat % preview
  const liveNavyFat = useMemo(() => {
    const neck = parseFloat(neckCm)
    const waist = parseFloat(waistCm)
    const hips = parseFloat(hipsCm)
    if (isNaN(neck) || isNaN(waist) || neck <= 0 || waist <= 0) return null
    return computeNavyFatPct(waist, neck, view.height_cm, view.sex, isNaN(hips) ? undefined : hips)
  }, [neckCm, waistCm, hipsCm, view.height_cm, view.sex])

  const invalidateMeasures = () => {
    void queryClient.invalidateQueries({ queryKey: ['weight'] })
  }

  const resetMeasureForm = () => {
    setEditingMeasure(null)
    setMDate(todayStr)
    setNeckCm('')
    setWaistCm('')
    setHipsCm('')
    setMNote('')
  }

  // Save measurement mutation
  const measureMutation = useConflictMutation({
    mutationFn: async ({ override }) => {
      if (editingMeasure !== null) {
        // An edit hands over the whole row: a field emptied in the form is removed.
        const body = buildMeasureBody({ date: mDate, neck: neckCm, waist: waistCm, hips: hipsCm, note: mNote })
        if (body === null) throw new InvalidError('')
        await ok(
          api.PATCH('/api/v1/weight/measures/{measurement_id}', {
            params: { path: { measurement_id: editingMeasure.id } },
            body: { ...body, override },
          }),
        )
        return
      }
      const neck = parseFloat(neckCm)
      const waist = parseFloat(waistCm)
      const hips = hipsCm ? parseFloat(hipsCm) : undefined
      await ok(
        api.POST('/api/v1/weight/measures', {
          body: {
            date: mDate,
            neck_cm: isNaN(neck) ? undefined : neck,
            waist_cm: isNaN(waist) ? undefined : waist,
            hips_cm: hips && !isNaN(hips) ? hips : undefined,
            note: mNote.trim() || undefined,
            override,
          },
        }),
      )
    },
    fallbackErrorMessage: t('app.save_failed'),
    onSuccess: () => {
      invalidateMeasures()
      toast(t('app.weight.measures_saved'))
      resetMeasureForm()
    },
    onError: (err) => toast(failText(err, t('app.save_failed')), { icon: 'warn' }),
  })

  const startMeasureEdit = (m: Measurement) => {
    measureMutation.clearConflict()
    setEditingMeasure({ id: m.id, date: m.date })
    setMDate(m.date)
    setNeckCm(m.neck_cm == null ? '' : String(m.neck_cm))
    setWaistCm(m.waist_cm == null ? '' : String(m.waist_cm))
    setHipsCm(m.hips_cm == null ? '' : String(m.hips_cm))
    setMNote(m.note ?? '')
    setActivePane('measure')
    // The form can sit a screen away from the row that opened it.
    measureForm.current?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }

  const deleteFailed = () => toast(t('app.delete_failed'), { icon: 'warn' })
  const deleted = () => {
    invalidateMeasures()
    toast(t('common.deleted'))
  }

  // Delete measurement mutation
  const deleteMeasureMutation = useMutation({
    mutationFn: (id: number) => ok(api.DELETE('/api/v1/weight/measures/{measurement_id}', { params: { path: { measurement_id: id } } })),
    onSuccess: deleted,
    onError: deleteFailed,
  })

  // Save noise marker mutation
  const noiseMutation = useMutation({
    mutationFn: () =>
      ok(
        api.POST('/api/v1/weight/noise-markers', {
          body: {
            start_date: nStart,
            end_date: nEnd || undefined,
            reason: nReason.trim(),
            direction: nDirection === 'n' ? undefined : nDirection,
          },
        }),
      ),
    onSuccess: () => {
      invalidateMeasures()
      toast(t('app.saved'))
      setNReason('')
      setNEnd('')
    },
    onError: (err) => toast(failText(err, t('app.save_failed')), { icon: 'warn' }),
  })

  // Delete noise marker mutation
  const deleteNoiseMutation = useMutation({
    mutationFn: (id: number) => ok(api.DELETE('/api/v1/weight/noise-markers/{marker_id}', { params: { path: { marker_id: id } } })),
    onSuccess: deleted,
    onError: deleteFailed,
  })

  // Upload photo mutation
  const photoMutation = useMutation({
    mutationFn: async () => {
      if (!phFiles || phFiles.length === 0) return
      for (let i = 0; i < phFiles.length; i++) {
        const file = phFiles.item(i)
        if (!file) continue
        const fd = new FormData()
        fd.append('file', file)
        fd.append('date', phDate)
        if (phNote) fd.append('note', phNote)
        const res = await fetch('/api/v1/weight/photos', {
          method: 'POST',
          body: fd,
          credentials: 'same-origin',
        })
        if (!res.ok) throw new RequestError(res.status)
      }
    },
    onSuccess: () => {
      invalidateMeasures()
      toast(t('app.saved'))
      setPhFiles(null)
      setPhNote('')
    },
    onError: () => {
      // Some of the files may have gone through before the one that failed.
      invalidateMeasures()
      toast(t('app.upload_failed'), { icon: 'warn' })
    },
  })

  // Delete photo mutation
  const deletePhotoMutation = useMutation({
    mutationFn: (id: number) => ok(api.DELETE('/api/v1/weight/photos/{photo_id}', { params: { path: { photo_id: id } } })),
    onSuccess: deleted,
    onError: deleteFailed,
  })

  // Upload BIA scan file
  const handleScanUpload = async () => {
    if (!scanFile) return
    setIsScanning(true)
    try {
      const fd = new FormData()
      fd.append('file', scanFile)
      const res = await fetch('/api/v1/weight/body-scans/upload', {
        method: 'POST',
        body: fd,
        credentials: 'same-origin',
      })
      if (!res.ok) throw new RequestError(res.status)
      const json = (await res.json()) as BodyScanUploadResponse
      const scan = json.scan
      if (!json.ok || scan === undefined || scan === null) {
        toast(t(json.reason === 'not_configured' ? 'app.weight.scan_no_llm' : 'body.upload.error'), { icon: 'warn' })
        return
      }
      setPreviewFileKey(scan.file_key)
      setPreviewRawId(scan.raw_payload_id)
      setPreviewDate(scan.date)
      setPreviewDevice(scan.device ?? '')
      setPreviewMetrics(toScanPreview(scan.metrics ?? []))
    } catch {
      toast(t('body.upload.error'), { icon: 'warn' })
    } finally {
      setIsScanning(false)
    }
  }

  // Confirm BIA scan
  const confirmScanMutation = useConflictMutation({
    mutationFn: async ({ override }) => {
      const metrics = readScanMetrics(previewMetrics)
      if (metrics === null) throw new InvalidError(t('app.weight.scan_value_invalid'))
      await ok(
        api.POST('/api/v1/weight/body-scans/confirm', {
          body: {
            file_key: previewFileKey,
            raw_payload_id: previewRawId,
            date: previewDate,
            device: previewDevice,
            metrics,
            override,
          },
        }),
      )
    },
    fallbackErrorMessage: t('app.save_failed'),
    onSuccess: () => {
      invalidateMeasures()
      toast(t('app.weight.scan_saved'))
      setScanFile(null)
      setPreviewFileKey('')
      setPreviewRawId(null)
      setPreviewMetrics([])
    },
    onError: (err) => toast(failText(err, t('app.save_failed')), { icon: 'warn' }),
  })

  // Delete BIA scan
  const deleteScanMutation = useMutation({
    mutationFn: (id: number) => ok(api.DELETE('/api/v1/weight/body-scans/{scan_id}', { params: { path: { scan_id: id } } })),
    onSuccess: deleted,
    onError: deleteFailed,
  })

  const weekDelta = view.week_delta_kg ?? null
  const drop = weekDelta !== null && weekDelta <= 0
  const latestWeight = view.latest_kg ?? null
  const average7 = view.average7 ?? null
  const bodyFat = view.body_fat_pct ?? null
  const measurements = view.measurements ?? []
  const noiseMarkers = view.noise_markers ?? []
  const photos = view.photos ?? []
  const scans = view.scans ?? []
  const headlineMetrics = view.headline_metrics ?? []
  // The last tape reading is what the empty fields hint at — nothing when there is none.
  const lastTape = measurements.find((m) => m.source !== 'scan')
  const hint = (value: number | null | undefined) => (value == null ? '' : formatCompact(value, lang))
  const underHero = [
    average7 === null ? null : t('app.weight.avg7', { avg: formatNumber(average7, lang) }),
    bodyFat === null
      ? null
      : view.body_fat_source == null
        ? t('app.weight.fat', { fat: formatPercent(bodyFat, lang, 1) })
        : t('app.weight.fat_from', { fat: formatPercent(bodyFat, lang, 1), source: view.body_fat_source }),
  ].filter((line): line is string => line !== null)

  return (
    <>
      <TopBar title={t('app.title.measures')} />
      <Headline title={t('app.title.measures')}>
        <div className="fig-hero">
          <div className="big" data-fig="weight">
            {latestWeight === null ? '—' : <Odometer value={formatNumber(latestWeight, lang)} />}
            <span className="unit">{t('app.unit.kg')}</span>
          </div>
          <div className="side">
            {weekDelta !== null && (
              <Delta tone={drop ? 'good' : undefined} icon={drop ? 'down' : 'up'}>
                {t('app.weight.week_delta', { value: formatNumber(Math.abs(weekDelta), lang) })}
              </Delta>
            )}
            {underHero.length > 0 && <span className="sub">{underHero.join(' · ')}</span>}
          </div>
        </div>
      </Headline>
      <DomainAlerts domain="weight" scope="weight" />

      <div className="grid rev">
        {/* Left Column: Input Forms & Markers */}
        <div className="c5">
          <Section title={t('app.weight.new_entry')}>
            <div className="panel">
              <Segmented
                value={activePane}
                onChange={setActivePane}
                label={t('app.weight.new_entry')}
                options={[
                  { id: 'measure', label: t('app.weight.tab_measures') },
                  { id: 'noise', label: t('app.weight.tab_noise') },
                  { id: 'photo', label: t('app.weight.tab_photo') },
                  { id: 'body', label: t('app.weight.tab_body') },
                ]}
              />

              <div className="mt-s4">
                {activePane === 'measure' && (
                  <form ref={measureForm} onSubmit={(e) => { e.preventDefault(); measureMutation.mutate() }}>
                    {editingMeasure !== null ? (
                      <p className="sub editing-mark">
                        {t('weight.editing_prefix')} · {longDate(parseIsoDate(editingMeasure.date), lang)}
                      </p>
                    ) : null}
                    <div className="fld">
                      <label>{t('common.date')}</label>
                      <input type="date" className="input" value={mDate} onChange={(e) => setMDate(e.target.value)} required />
                    </div>
                    <div className="g2">
                      <div className="fld">
                        <label>{t('app.weight.neck_cm')}</label>
                        <input
                          type="number"
                          step="0.1"
                          placeholder={hint(lastTape?.neck_cm)}
                          className="input"
                          value={neckCm}
                          onChange={(e) => setNeckCm(e.target.value)}
                        />
                      </div>
                      <div className="fld">
                        <label>{t('app.weight.waist_cm')}</label>
                        <input
                          type="number"
                          step="0.1"
                          placeholder={hint(lastTape?.waist_cm)}
                          className="input"
                          value={waistCm}
                          onChange={(e) => setWaistCm(e.target.value)}
                        />
                      </div>
                    </div>
                    {view.sex === 'female' && (
                      <div className="fld">
                        <label>{t('app.weight.hips_cm')}</label>
                        <input
                          type="number"
                          step="0.1"
                          placeholder={hint(lastTape?.hips_cm)}
                          className="input"
                          value={hipsCm}
                          onChange={(e) => setHipsCm(e.target.value)}
                        />
                      </div>
                    )}
                    <div className="fld">
                      <label>{t('app.weight.note_optional')}</label>
                      <input
                        type="text"
                        placeholder={t('app.weight.note_placeholder')}
                        className="input"
                        value={mNote}
                        onChange={(e) => setMNote(e.target.value)}
                      />
                    </div>
                    <p className="sub navy-line">
                      {t('app.weight.navy_immediate')}:{' '}
                      <span className="navyfig">{liveNavyFat !== null ? formatPercent(liveNavyFat, lang, 1) : '—'}</span>
                    </p>
                    <ConflictAlert
                      violations={measureMutation.violations}
                      onFix={() => measureMutation.clearConflict()}
                      onSaveAnyway={() => void measureMutation.retryWithOverride()}
                    />
                    <div className="form-acts">
                      <button type="submit" className="btn grow" disabled={measureMutation.isPending}>
                        {editingMeasure !== null ? t('weight.update_measures') : t('app.weight.save_measures')}
                      </button>
                      {editingMeasure !== null ? (
                        <button type="button" className="ghost" onClick={resetMeasureForm}>
                          {t('app.cancel')}
                        </button>
                      ) : null}
                    </div>
                  </form>
                )}

                {activePane === 'noise' && (
                  <form onSubmit={(e) => { e.preventDefault(); noiseMutation.mutate() }}>
                    <div className="g2">
                      <div className="fld">
                        <label>{t('app.weight.start_date')}</label>
                        <input type="date" className="input" value={nStart} onChange={(e) => setNStart(e.target.value)} required />
                      </div>
                      <div className="fld">
                        <label>{t('app.weight.end_date')}</label>
                        <input type="date" className="input" value={nEnd} onChange={(e) => setNEnd(e.target.value)} />
                      </div>
                    </div>
                    <div className="fld">
                      <label>{t('app.weight.noise_reason')}</label>
                      <input
                        type="text"
                        placeholder={t('weight.noise_placeholder')}
                        className="input"
                        value={nReason}
                        onChange={(e) => setNReason(e.target.value)}
                        required
                      />
                    </div>
                    <div className="fld">
                      <label>{t('app.weight.distortion_dir')}</label>
                      <select
                        className="input"
                        value={nDirection}
                        onChange={(e) => setNDirection(e.target.value as 'n' | 'u' | 'd')}
                      >
                        <option value="n">{t('app.weight.dir_unknown')}</option>
                        <option value="u">{t('app.weight.dir_up')}</option>
                        <option value="d">{t('app.weight.dir_down')}</option>
                      </select>
                    </div>
                    <div className="form-acts">
                      <button type="submit" className="btn grow" disabled={noiseMutation.isPending}>
                        {t('app.weight.exclude_period')}
                      </button>
                    </div>
                  </form>
                )}

                {activePane === 'photo' && (
                  <form onSubmit={(e) => { e.preventDefault(); photoMutation.mutate() }}>
                    <div className="fld">
                      <label>{t('common.date')}</label>
                      <input type="date" className="input" value={phDate} onChange={(e) => setPhDate(e.target.value)} required />
                    </div>
                    <div className="fld">
                      <label>{t('app.weight.photo_files')}</label>
                      <input
                        type="file"
                        accept="image/*"
                        multiple
                        className="input"
                        onChange={(e) => setPhFiles(e.target.files)}
                        required
                      />
                    </div>
                    <div className="fld">
                      <label>{t('app.weight.note_optional')}</label>
                      <input
                        type="text"
                        className="input"
                        value={phNote}
                        onChange={(e) => setPhNote(e.target.value)}
                      />
                    </div>
                    <div className="form-acts">
                      <button type="submit" className="btn grow" disabled={photoMutation.isPending}>
                        {t('app.weight.upload_photos')}
                      </button>
                    </div>
                  </form>
                )}

                {activePane === 'body' && (
                  <div>
                    {!previewFileKey ? (
                      <div>
                        <p className="sub scan-lead">{t('app.weight.body_comp_sub')}</p>
                        <div className="fld">
                          <input
                            type="file"
                            accept="image/*,application/pdf"
                            className="input"
                            onChange={(e) => setScanFile(e.target.files?.[0] || null)}
                          />
                        </div>
                        <div className="form-acts">
                          <button
                            type="button"
                            className="btn grow"
                            disabled={!scanFile || isScanning}
                            onClick={handleScanUpload}
                          >
                            {isScanning ? t('app.weight.scanning') : t('app.weight.recognize_scan')}
                          </button>
                        </div>
                      </div>
                    ) : (
                      <form onSubmit={(e) => { e.preventDefault(); confirmScanMutation.mutate() }}>
                        <h4 className="pv-title">{t('app.weight.verify_metrics')}</h4>
                        <div className="g2">
                          <div className="fld">
                            <label>{t('common.date')}</label>
                            <input
                              type="date"
                              className="input"
                              value={previewDate}
                              onChange={(e) => setPreviewDate(e.target.value)}
                              required
                            />
                          </div>
                          <div className="fld">
                            <label>{t('app.weight.device')}</label>
                            <input
                              type="text"
                              className="input"
                              value={previewDevice}
                              onChange={(e) => setPreviewDevice(e.target.value)}
                              required
                            />
                          </div>
                        </div>

                        <div className="pv">
                          <div className="pv-h">
                            <span>{t('app.weight.metric')}</span>
                            <span>{t('app.weight.value')}</span>
                            <span>{t('app.weight.unit')}</span>
                            <span />
                          </div>
                          {previewMetrics.map((m, idx) => (
                            <div key={idx} className="pv-r">
                              <input
                                className="input sm"
                                value={m.label}
                                onChange={(e) => {
                                  const label = e.target.value
                                  setPreviewMetrics((prev) =>
                                    prev.map((item, i) => (i === idx ? { ...item, label } : item))
                                  )
                                }}
                              />
                              <input
                                className="input sm num"
                                inputMode="decimal"
                                value={m.value}
                                onChange={(e) => {
                                  const value = e.target.value
                                  setPreviewMetrics((prev) =>
                                    prev.map((item, i) => (i === idx ? { ...item, value } : item))
                                  )
                                }}
                              />
                              <input
                                className="input sm"
                                value={m.unit || ''}
                                onChange={(e) => {
                                  const unit = e.target.value
                                  setPreviewMetrics((prev) =>
                                    prev.map((item, i) => (i === idx ? { ...item, unit } : item))
                                  )
                                }}
                              />
                              <button
                                type="button"
                                className="ibtn"
                                onClick={() => setPreviewMetrics((prev) => prev.filter((_, i) => i !== idx))}
                              >
                                <Icon name="x" />
                              </button>
                            </div>
                          ))}
                        </div>

                        <ConflictAlert
                          violations={confirmScanMutation.violations}
                          onFix={() => confirmScanMutation.clearConflict()}
                          onSaveAnyway={() => void confirmScanMutation.retryWithOverride()}
                        />
                        <div className="form-acts">
                          <button
                            type="button"
                            className="ghost"
                            onClick={() => {
                              setPreviewMetrics([
                                ...previewMetrics,
                                { category: 'custom', label: t('app.weight.new_metric'), value: '', unit: '' },
                              ])
                            }}
                          >
                            + {t('app.weight.add_metric')}
                          </button>
                          <button type="submit" className="btn grow" disabled={confirmScanMutation.isPending}>
                            {t('app.weight.save_scan')}
                          </button>
                          <button type="button" className="ghost" onClick={() => setPreviewFileKey('')}>
                            {t('app.cancel')}
                          </button>
                        </div>
                      </form>
                    )}
                  </div>
                )}
              </div>
            </div>
          </Section>

          {/* Noise Markers List */}
          <Section title={t('app.weight.excluded_periods')}>
            <div className="rows">
              {noiseMarkers.length === 0 ? (
                <div className="row"><span className="m">{t('app.empty')}</span></div>
              ) : (
                noiseMarkers.map((n) => (
                  <div key={n.id} className="row r-kv">
                    <div>
                      <div className="t num">
                        {shortDate(parseIsoDate(n.start_date), lang)}{' '}
                        {n.end_date
                          ? `— ${shortDate(parseIsoDate(n.end_date), lang)}`
                          : `(${t('app.active')})`}
                      </div>
                      <div className="m">
                        {n.reason} · {n.direction === 'up' ? t('app.weight.noise_up') : n.direction === 'down' ? t('app.weight.noise_down') : t('app.weight.noise_flat')}
                      </div>
                    </div>
                    <ConfirmButton label={t('app.delete')} onConfirm={() => deleteNoiseMutation.mutate(n.id)} />
                  </div>
                ))
              )}
            </div>
          </Section>

          {/* Progress Gallery */}
          <Section title={t('app.weight.progress_gallery')}>
            <div className="ribbon">
              {photos.length === 0 ? (
                <span className="m ribbon-empty">{t('app.empty')}</span>
              ) : (
                photos.map((ph) => (
                  <div key={ph.id} className="ph-tile">
                    <div className="im">
                      <img src={ph.url} alt={ph.note ?? t('app.weight.tab_photo')} />
                    </div>
                    <span className="m num">{shortDate(parseIsoDate(ph.date), lang)}</span>
                    <ConfirmButton label={t('app.delete')} onConfirm={() => deletePhotoMutation.mutate(ph.id)} />
                  </div>
                ))
              )}
            </div>
          </Section>
        </div>

        {/* Right Column: Body Composition & Measurement History */}
        <div className="c7">
          {/* Body Composition 6-grid */}
          {headlineMetrics.length > 0 && (
            <Section title={t('app.weight.body_comp_headline')}>
              <div className="figs six">
                {headlineMetrics.map((m, idx) => (
                  <div key={idx} className="f">
                    <div className="f-v">
                      {formatCompact(m.value, lang, 3)}
                      {m.unit && <span className="u">{m.unit}</span>}
                    </div>
                    <div className="f-l">{m.label}</div>
                  </div>
                ))}
              </div>
            </Section>
          )}

          {/* Circumference History */}
          <Section title={t('app.weight.measures_history')}>
            <div className="rows">
              {measurements.length === 0 ? (
                <div className="row"><span className="m">{t('app.empty')}</span></div>
              ) : (
                measurements.map((m) => (
                  <div key={`${m.source}:${m.id}`} className="row t-meas">
                    <div>
                      <div className="t">{longDate(parseIsoDate(m.date), lang)}</div>
                      <div className="m hd">
                        {[
                          m.neck_cm != null ? `${t('app.weight.neck_short')} ${formatNumber(m.neck_cm, lang)}` : null,
                          m.waist_cm != null ? `${t('app.weight.waist_short')} ${formatNumber(m.waist_cm, lang)}` : null,
                          m.lbm_kg != null ? `LBM ${formatNumber(m.lbm_kg, lang)} ${t('app.unit.kg')}` : null,
                        ].filter(Boolean).join(' · ') || '—'}
                      </div>
                    </div>
                    <div className="v hs">{m.neck_cm != null ? formatNumber(m.neck_cm, lang) : '—'}</div>
                    <div className="v hs">{m.waist_cm != null ? formatNumber(m.waist_cm, lang) : '—'}</div>
                    <div className="v">{m.body_fat_pct != null ? formatPercent(m.body_fat_pct, lang, 1) : '—'}</div>
                    <div className="v hs">
                      {m.lbm_kg != null ? formatNumber(m.lbm_kg, lang) : '—'}
                      {m.lbm_kg != null && <span className="u">{t('app.unit.kg')}</span>}
                    </div>
                    <div className="acts">
                      {/* Only a tape measurement is edited here; a scan's numbers are the device's. */}
                      {m.source === 'navy' ? (
                        <button type="button" className="ibtn" onClick={() => startMeasureEdit(m)} aria-label={t('common.edit')} title={t('common.edit')}>
                          <Icon name="edit" />
                        </button>
                      ) : null}
                      {/* A row that came from a scan is the scan: it is deleted as one, by its own id. */}
                      <ConfirmButton
                        label={t('app.delete')}
                        onConfirm={() => (m.source === 'scan' ? deleteScanMutation : deleteMeasureMutation).mutate(m.id)}
                      />
                    </div>
                  </div>
                ))
              )}
            </div>
          </Section>

          {/* BIA Scan History Accordion */}
          <Section title={t('app.weight.scans_history')}>
            <div className="rows">
              {scans.length === 0 ? (
                <div className="row"><span className="m">{t('app.empty')}</span></div>
              ) : (
                scans.map((s) => (
                  <Disclosure
                    key={s.id}
                    open={openScanId === s.id}
                    onToggle={() => setOpenScanId(openScanId === s.id ? null : s.id)}
                    title={longDate(parseIsoDate(s.date), lang)}
                    sub={[s.device, metricsCount(s.metrics_count)].filter(Boolean).join(' · ')}
                    actions={
                      <ConfirmButton label={t('app.delete')} onConfirm={() => deleteScanMutation.mutate(s.id)} />
                    }
                  >
                    <div className="disc-body">
                      <div className="rows">
                        {(s.metrics ?? []).map((met, mIdx) => (
                          <div key={mIdx} className="row r-kv tight">
                            <span className="t plain">{met.label}</span>
                            <span className="v">
                              {formatCompact(met.value, lang, 3)}
                              {met.unit && <span className="u">{met.unit}</span>}
                            </span>
                          </div>
                        ))}
                      </div>
                    </div>
                  </Disclosure>
                ))
              )}
            </div>
          </Section>
        </div>
      </div>
    </>
  )
}
