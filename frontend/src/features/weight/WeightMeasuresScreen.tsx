import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '@/api/client'
import { ConflictAlert } from '@/components/controls/ConflictAlert'
import { Delta } from '@/components/controls/Marks'
import { Odometer } from '@/components/controls/Odometer'
import { Segmented } from '@/components/controls/Segmented'
import { Section } from '@/components/controls/Section'
import { Icon } from '@/components/icons/Icon'
import { Headline, TopBar } from '@/components/shell/PageHead'
import { toast } from '@/components/controls/toast'
import { useT } from '@/i18n/useT'
import { cx } from '@/lib/cx'
import { longDate, parseIsoDate, shortDate, toIsoDate } from '@/lib/dates'
import { formatNumber } from '@/lib/format'
import { useConflictMutation } from '@/lib/useConflictMutation'
import { computeNavyFatPct } from './navy'
import type { components } from '@/api/schema'
import './weight.css'

type WeightMeasuresView = components['schemas']['WeightMeasuresView']
type BodyScanMetricItem = components['schemas']['BodyScanMetricItem']

export const measuresQuery = {
  queryKey: ['weight', 'measures'],
  queryFn: async (): Promise<WeightMeasuresView> => {
    const { data } = await api.GET('/api/v1/weight/measures')
    if (!data) throw new Error('Could not load measures')
    return data
  },
}

export default function WeightMeasuresScreen() {
  const { t, lang } = useT()
  const queryClient = useQueryClient()
  const { data: view } = useQuery(measuresQuery)

  const [activePane, setActivePane] = useState<'measure' | 'noise' | 'photo' | 'body'>('measure')
  const [openScanId, setOpenScanId] = useState<number | null>(null)

  // Measure form state
  const todayStr = toIsoDate(new Date())
  const [mDate, setMDate] = useState(todayStr)
  const [neckCm, setNeckCm] = useState('')
  const [waistCm, setWaistCm] = useState('')
  const [hipsCm, setHipsCm] = useState('')
  const [mNote, setMNote] = useState('')

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
  const [previewMetrics, setPreviewMetrics] = useState<BodyScanMetricItem[]>([])
  const [previewDate, setPreviewDate] = useState(todayStr)
  const [previewDevice, setPreviewDevice] = useState('InBody 770')
  const [previewFileKey, setPreviewFileKey] = useState('')
  const [isScanning, setIsScanning] = useState(false)

  // Calculated Navy Fat % preview
  const liveNavyFat = useMemo(() => {
    const neck = parseFloat(neckCm)
    const waist = parseFloat(waistCm)
    const hips = parseFloat(hipsCm)
    const height = view?.height_cm ?? 190
    const sex = view?.sex ?? 'male'
    if (isNaN(neck) || isNaN(waist) || neck <= 0 || waist <= 0) return null
    return computeNavyFatPct(waist, neck, height, sex, isNaN(hips) ? undefined : hips)
  }, [neckCm, waistCm, hipsCm, view?.height_cm, view?.sex])

  const invalidateMeasures = () => {
    void queryClient.invalidateQueries({ queryKey: ['weight'] })
  }

  // Save measurement mutation
  const measureMutation = useConflictMutation({
    mutationFn: async ({ override }) => {
      const neck = parseFloat(neckCm)
      const waist = parseFloat(waistCm)
      const hips = hipsCm ? parseFloat(hipsCm) : undefined
      await api.POST('/api/v1/weight/measures', {
        body: {
          date: mDate,
          neck_cm: isNaN(neck) ? undefined : neck,
          waist_cm: isNaN(waist) ? undefined : waist,
          hips_cm: hips && !isNaN(hips) ? hips : undefined,
          note: mNote.trim() || undefined,
          override,
        },
      })
    },
    onSuccess: () => {
      invalidateMeasures()
      toast(t('app.weight.measures_saved'))
      setNeckCm('')
      setWaistCm('')
      setHipsCm('')
      setMNote('')
    },
    onError: (err) => toast(err.message),
  })

  // Delete measurement mutation
  const deleteMeasureMutation = useMutation({
    mutationFn: async (id: number) => {
      await api.DELETE('/api/v1/weight/measures/{measurement_id}', { params: { path: { measurement_id: id } } })
    },
    onSuccess: () => {
      invalidateMeasures()
      toast(t('app.saved'))
    },
  })

  // Save noise marker mutation
  const noiseMutation = useMutation({
    mutationFn: async () => {
      await api.POST('/api/v1/weight/noise-markers', {
        body: {
          start_date: nStart,
          end_date: nEnd || undefined,
          reason: nReason.trim(),
          direction: nDirection === 'n' ? undefined : nDirection,
        },
      })
    },
    onSuccess: () => {
      invalidateMeasures()
      toast(t('app.saved'))
      setNReason('')
      setNEnd('')
    },
    onError: (err) => toast(err.message),
  })

  // Delete noise marker mutation
  const deleteNoiseMutation = useMutation({
    mutationFn: async (id: number) => {
      await api.DELETE('/api/v1/weight/noise-markers/{marker_id}', { params: { path: { marker_id: id } } })
    },
    onSuccess: () => {
      invalidateMeasures()
      toast(t('app.saved'))
    },
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
        await fetch('/api/v1/weight/photos', {
          method: 'POST',
          body: fd,
          credentials: 'same-origin',
        })
      }
    },
    onSuccess: () => {
      invalidateMeasures()
      toast(t('app.saved'))
      setPhFiles(null)
      setPhNote('')
    },
  })

  // Delete photo mutation
  const deletePhotoMutation = useMutation({
    mutationFn: async (id: number) => {
      await api.DELETE('/api/v1/weight/photos/{photo_id}', { params: { path: { photo_id: id } } })
    },
    onSuccess: () => {
      invalidateMeasures()
      toast(t('app.saved'))
    },
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
      if (!res.ok) throw new Error('Upload failed')
      const json = await res.json()
      setPreviewFileKey(json.file_key)
      setPreviewDate(json.date || todayStr)
      setPreviewDevice(json.device || 'InBody 770')
      setPreviewMetrics(json.metrics || [])
    } catch (err: unknown) {
      toast(err instanceof Error ? err.message : 'Error')
    } finally {
      setIsScanning(false)
    }
  }

  // Confirm BIA scan
  const confirmScanMutation = useConflictMutation({
    mutationFn: async ({ override }) => {
      await api.POST('/api/v1/weight/body-scans/confirm', {
        body: {
          file_key: previewFileKey,
          date: previewDate,
          device: previewDevice,
          metrics: previewMetrics,
          override,
        },
      })
    },
    onSuccess: () => {
      invalidateMeasures()
      toast(t('app.weight.scan_saved'))
      setScanFile(null)
      setPreviewFileKey('')
      setPreviewMetrics([])
    },
    onError: (err) => toast(err.message),
  })

  // Delete BIA scan
  const deleteScanMutation = useMutation({
    mutationFn: async (id: number) => {
      await api.DELETE('/api/v1/weight/body-scans/{scan_id}', { params: { path: { scan_id: id } } })
    },
    onSuccess: () => {
      invalidateMeasures()
      toast(t('app.saved'))
    },
  })

  const drop = (view?.week_delta_kg ?? 0) <= 0
  const latestWeight = view?.latest_kg ?? 0
  const measurements = view?.measurements ?? []
  const noiseMarkers = view?.noise_markers ?? []
  const photos = view?.photos ?? []
  const scans = view?.scans ?? []
  const headlineMetrics = view?.headline_metrics ?? []

  return (
    <>
      <TopBar title={t('app.title.measures')} />
      <Headline title={t('app.title.measures')}>
        <div className="fig-hero">
          <div className="big" data-fig="weight">
            <Odometer value={formatNumber(latestWeight, lang)} />
            <span className="unit">{t('app.unit.kg')}</span>
          </div>
          <div className="side">
            <Delta tone={drop ? 'good' : undefined} icon={drop ? 'down' : 'up'}>
              {t('app.weight.week_delta', { value: formatNumber(Math.abs(view?.week_delta_kg ?? 0), lang) })}
            </Delta>
            <span className="sub">
              {t('app.weight.avg_line', {
                avg: formatNumber(view?.average7 ?? 0, lang),
                fat: formatNumber(view?.body_fat_pct ?? 0, lang),
              })}
            </span>
          </div>
        </div>
      </Headline>

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

              <div style={{ marginTop: '16px' }}>
                {activePane === 'measure' && (
                  <form onSubmit={(e) => { e.preventDefault(); measureMutation.mutate() }}>
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
                          placeholder={formatNumber(38, lang)}
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
                          placeholder={formatNumber(85, lang)}
                          className="input"
                          value={waistCm}
                          onChange={(e) => setWaistCm(e.target.value)}
                        />
                      </div>
                    </div>
                    {view?.sex === 'female' && (
                      <div className="fld">
                        <label>{t('app.weight.hips_cm')}</label>
                        <input
                          type="number"
                          step="0.1"
                          placeholder={formatNumber(95, lang)}
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
                    <p className="sub" style={{ margin: '8px 0 16px' }}>
                      {t('app.weight.navy_immediate')}:{' '}
                      <span className="navyfig">
                        {liveNavyFat !== null ? `${formatNumber(liveNavyFat, lang)} %` : '—'}
                      </span>
                    </p>
                    <ConflictAlert
                      violations={measureMutation.violations}
                      onFix={() => measureMutation.clearConflict()}
                      onSaveAnyway={() => void measureMutation.retryWithOverride()}
                    />
                    <div className="form-acts">
                      <button type="submit" className="btn grow" disabled={measureMutation.isPending}>
                        {t('app.weight.save_measures')}
                      </button>
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
                        <p className="sub" style={{ margin: '0 0 12px' }}>{t('app.weight.body_comp_sub')}</p>
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
                        <h4 style={{ margin: '0 0 8px' }}>{t('app.weight.verify_metrics')}</h4>
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
                                value={m.value}
                                onChange={(e) => {
                                  const val = parseFloat(e.target.value) || 0
                                  setPreviewMetrics((prev) =>
                                    prev.map((item, i) => (i === idx ? { ...item, value: val } : item))
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
                        <div className="form-acts" style={{ marginTop: '12px' }}>
                          <button
                            type="button"
                            className="ghost"
                            onClick={() => {
                              setPreviewMetrics([
                                ...previewMetrics,
                                { category: 'custom', label: t('app.weight.new_metric'), value: 0, unit: '' },
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
                  <div key={n.id} className="row" style={{ gridTemplateColumns: 'minmax(0, 1fr) auto' }}>
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
                    <button
                      type="button"
                      className="ibtn danger"
                      onClick={() => deleteNoiseMutation.mutate(n.id)}
                      aria-label={t('app.delete')}
                    >
                      <Icon name="trash" />
                    </button>
                  </div>
                ))
              )}
            </div>
          </Section>

          {/* Progress Gallery */}
          <Section title={t('app.weight.progress_gallery')}>
            <div className="ribbon">
              {photos.length === 0 ? (
                <span className="m" style={{ padding: '8px 0' }}>{t('app.empty')}</span>
              ) : (
                photos.map((ph) => (
                  <div key={ph.id} className="ph-tile">
                    <div className="im">
                      <img src={`/static/uploads/${ph.file_key}`} alt={ph.note || 'Photo'} />
                    </div>
                    <span className="m num">{shortDate(parseIsoDate(ph.date), lang)}</span>
                    <button
                      type="button"
                      className="ibtn danger"
                      onClick={() => deletePhotoMutation.mutate(ph.id)}
                      style={{ fontSize: '11px' }}
                    >
                      <Icon name="trash" />
                    </button>
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
                      {typeof m.value === 'number' ? formatNumber(m.value, lang) : m.value}
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
                  <div key={m.id} className="row t-meas">
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
                    <div className="v">
                      {m.body_fat_pct != null ? formatNumber(m.body_fat_pct, lang) : '—'}
                      <span className="u">%</span>
                    </div>
                    <div className="v hs">
                      {m.lbm_kg != null ? formatNumber(m.lbm_kg, lang) : '—'}
                      <span className="u">{t('app.unit.kg')}</span>
                    </div>
                    <div className="acts">
                      <button
                        type="button"
                        className="ibtn danger"
                        onClick={() => deleteMeasureMutation.mutate(m.id)}
                        aria-label={t('app.delete')}
                      >
                        <Icon name="trash" />
                      </button>
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
                scans.map((s) => {
                  const isOpen = openScanId === s.id
                  return (
                    <div key={s.id} className={cx('acc', isOpen && 'open')}>
                      <div
                        className="row acc-h r-scan"
                        onClick={() => setOpenScanId(isOpen ? null : s.id)}
                        role="button"
                        tabIndex={0}
                      >
                        <Icon name={isOpen ? 'chevD' : 'chevR'} />
                        <div>
                          <div className="t">{longDate(parseIsoDate(s.date), lang)}</div>
                          <div className="m">{s.device} · {t('app.weight.metrics_count', { count: s.metrics_count })}</div>
                        </div>
                        <span className="acts" onClick={(e) => e.stopPropagation()}>
                          <button
                            type="button"
                            className="ibtn danger"
                            onClick={() => deleteScanMutation.mutate(s.id)}
                            aria-label={t('app.delete')}
                          >
                            <Icon name="trash" />
                          </button>
                        </span>
                      </div>
                      {isOpen && (
                        <div className="acc-b">
                          {s.metrics.map((met, mIdx) => (
                            <div key={mIdx} className="row kv" style={{ gridTemplateColumns: 'minmax(0, 1fr) auto' }}>
                              <span>{met.label}</span>
                              <span className="v">
                                {typeof met.value === 'number' ? formatNumber(met.value, lang) : met.value}{' '}
                                {met.unit && <span className="u">{met.unit}</span>}
                              </span>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  )
                })
              )}
            </div>
          </Section>
        </div>
      </div>
    </>
  )
}
