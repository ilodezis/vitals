import { useMemo, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { api } from '@/api/client'
import { ConflictAlert } from '@/components/controls/ConflictAlert'
import { Badge, Delta, TextButton } from '@/components/controls/Marks'
import { PrimaryButton, type PrimaryButtonHandle } from '@/components/controls/PrimaryButton'
import { Section } from '@/components/controls/Section'
import { toast } from '@/components/controls/toast'
import { Icon } from '@/components/icons/Icon'
import { Headline, Mast, TopBar } from '@/components/shell/PageHead'
import { useT } from '@/i18n/useT'
import { parseIsoDate, shortDate, toIsoDate } from '@/lib/dates'
import { formatNumber } from '@/lib/format'
import { useConflictMutation } from '@/lib/useConflictMutation'
import { useHrtView } from './useHrtView'
import './hrt.css'

export default function HrtScreen() {
  const { t, lang } = useT()
  const view = useHrtView()
  const queryClient = useQueryClient()

  const [doseModalOpen, setDoseModalOpen] = useState(false)
  const [cycleModalOpen, setCycleModalOpen] = useState(false)
  const [itemModalOpen, setItemModalOpen] = useState(false)
  const [sideEffectModalOpen, setSideEffectModalOpen] = useState(false)
  const [templateName, setTemplateName] = useState('')
  const doseButtonRef = useRef<PrimaryButtonHandle>(null)

  // Form states
  const todayStr = useMemo(() => toIsoDate(new Date()), [])
  const [doseDate, setDoseDate] = useState(todayStr)
  const [doseCompound, setDoseCompound] = useState(() => view.compounds[0]?.key ?? 'testosterone_cypionate')
  const [doseVal, setDoseVal] = useState('100')
  const [doseUnit, setDoseUnit] = useState('mg')
  const [doseSite, setDoseSite] = useState('glute_left')
  const [doseBrand, setDoseBrand] = useState('')
  const [doseNote, setDoseNote] = useState('')

  // Cycle form states
  const [cycleKind, setCycleKind] = useState('trt')
  const [cycleName, setCycleName] = useState('')
  const [cycleStart, setCycleStart] = useState(todayStr)
  const [cycleEnd, setCycleEnd] = useState('')

  // Item form states
  const [itemCompound, setItemCompound] = useState(() => view.compounds[0]?.key ?? 'testosterone_cypionate')
  const [itemDose, setItemDose] = useState('125')
  const [itemInterval, setItemInterval] = useState('3.5')
  const [itemStartWeek, setItemStartWeek] = useState('1')

  // Side effect form states
  const [seDate, setSeDate] = useState(todayStr)
  const [seType, setSeType] = useState('acne')
  const [seSev, setSeSev] = useState(2)
  const [seNote, setSeNote] = useState('')

  const activeC = view.cycle

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ['hrt'] })
    void queryClient.invalidateQueries({ queryKey: ['today'] })
  }

  // Dose submission
  const doseConflict = useConflictMutation({
    mutationFn: async ({ override }) => {
      const res = await api.POST('/api/v1/hrt/doses', {
        body: {
          date: doseDate,
          compoundKey: doseCompound,
          dose: parseFloat(doseVal) || 0,
          unit: doseUnit,
          site: doseSite || null,
          brand: doseBrand || null,
          note: doseNote || null,
          override,
        },
      })
      if (!res.data) throw new Error(t('app.error'))
      toast(t('common.saved'))
      setDoseModalOpen(false)
      refresh()
      return res.data
    },
    onError: (err) => {
      toast(err.message, { icon: 'warn' })
    },
  })

  // Delete dose
  const handleDeleteDose = async (id: number) => {
    try {
      await api.DELETE('/api/v1/hrt/doses/{dose_id}', { params: { path: { dose_id: id } } })
      toast(t('common.deleted'))
      refresh()
    } catch (err: any) {
      toast(err.message, { icon: 'warn' })
    }
  }

  // Cycle creation
  const handleCreateCycle = async (): Promise<boolean> => {
    try {
      const res = await api.POST('/api/v1/hrt/cycles', {
        body: {
          kind: cycleKind,
          name: cycleName || null,
          startDate: cycleStart,
          endDate: cycleEnd || null,
        },
      })
      if (res.data) {
        toast(t('common.saved'))
        setCycleModalOpen(false)
        refresh()
        return true
      }
      return false
    } catch (err: any) {
      toast(err.message, { icon: 'warn' })
      return false
    }
  }

  // Close cycle
  const handleCloseCycle = async () => {
    if (!activeC) return
    try {
      await api.POST('/api/v1/hrt/cycles/{cycle_id}/close', {
        params: { path: { cycle_id: activeC.id } },
        body: { endDate: todayStr },
      })
      toast(t('hrt.cycle_closed'))
      refresh()
    } catch (err: any) {
      toast(err.message, { icon: 'warn' })
    }
  }

  // Add compound item to cycle
  const handleAddItem = async (): Promise<boolean> => {
    if (!activeC) return false
    try {
      const res = await api.POST('/api/v1/hrt/cycles/{cycle_id}/items', {
        params: { path: { cycle_id: activeC.id } },
        body: {
          compoundKey: itemCompound,
          dose: parseFloat(itemDose) || 0,
          intervalDays: parseFloat(itemInterval) || 3.5,
          startWeek: parseInt(itemStartWeek, 10) || 1,
        },
      })
      if (res.data) {
        toast(t('common.saved'))
        setItemModalOpen(false)
        refresh()
        return true
      }
      return false
    } catch (err: any) {
      toast(err.message, { icon: 'warn' })
      return false
    }
  }

  // Delete compound item
  const handleDeleteItem = async (itemId: number) => {
    try {
      await api.DELETE('/api/v1/hrt/cycle-items/{item_id}', { params: { path: { item_id: itemId } } })
      toast(t('common.deleted'))
      refresh()
    } catch (err: any) {
      toast(err.message, { icon: 'warn' })
    }
  }

  // Save active cycle as template
  const handleSaveTemplate = async () => {
    if (!activeC || !templateName.trim()) return
    try {
      await api.POST('/api/v1/hrt/cycles/{cycle_id}/save-template', {
        params: { path: { cycle_id: activeC.id } },
        body: { name: templateName.trim() },
      })
      toast(t('hrt.template_saved'))
      setTemplateName('')
      refresh()
    } catch (err: any) {
      toast(err.message, { icon: 'warn' })
    }
  }

  // Apply template to start cycle
  const handleApplyTemplate = async (templateId: number) => {
    try {
      await api.POST('/api/v1/hrt/templates/{template_id}/create-cycle', {
        params: { path: { template_id: templateId } },
        body: { startDate: todayStr },
      })
      toast(t('hrt.cycle_started'))
      refresh()
    } catch (err: any) {
      toast(err.message, { icon: 'warn' })
    }
  }

  // Side effect log
  const handleCreateSideEffect = async (): Promise<boolean> => {
    try {
      await api.POST('/api/v1/hrt/side-effects', {
        body: {
          date: seDate,
          effectType: seType,
          severity: seSev,
          note: seNote || null,
        },
      })
      toast(t('common.saved'))
      setSideEffectModalOpen(false)
      refresh()
      return true
    } catch (err: any) {
      toast(err.message, { icon: 'warn' })
      return false
    }
  }

  // Delete side effect
  const handleDeleteSideEffect = async (id: number) => {
    try {
      await api.DELETE('/api/v1/hrt/side-effects/{effect_id}', { params: { path: { effect_id: id } } })
      toast(t('common.deleted'))
      refresh()
    } catch (err: any) {
      toast(err.message, { icon: 'warn' })
    }
  }

  // Release curve points calculation
  const releaseSvg = useMemo(() => {
    if (!view.release || view.release.length === 0) return null
    const pts = view.release
    const maxMg = Math.max(...pts.map((p) => p.total_mg), 1)
    const w = 500
    const h = 70
    const coords = pts.map((p, i) => {
      const x = (i / (pts.length - 1)) * w
      const y = h - (p.total_mg / maxMg) * (h - 8) - 4
      return `${x.toFixed(1)},${y.toFixed(1)}`
    })
    return { points: coords.join(' '), maxMg: formatNumber(maxMg, lang, 1) }
  }, [view.release, lang])

  const lastDoseVal = view.last ? parseFloat(view.last.dose) : NaN
  const lastDoseNum = !Number.isNaN(lastDoseVal) ? formatNumber(lastDoseVal, lang, 1) : (view.last?.dose ?? '—')

  return (
    <>
      <TopBar title={t('nav.hrt')} />
      <Mast
        screen="hrt"
        actions={
          <div className="hrt-acts">
            <TextButton icon="syringe" onClick={() => setDoseModalOpen(true)}>
              {t('hrt.add_dose')}
            </TextButton>
            {!activeC && (
              <TextButton icon="pulse" onClick={() => setCycleModalOpen(true)}>
                {t('hrt.start_cycle')}
              </TextButton>
            )}
          </div>
        }
      />
      <Headline title={t('nav.hrt')}>
        <div className="hrt-hero">
          <div className="big">
            {lastDoseNum}
            <span className="unit">{t('app.unit.mg')}</span>
          </div>
          <div className="side">
            <Badge tone="violet">{view.last ? view.last.name : t('hrt.no_active_dose')}</Badge>
            <span className="sub">
              {view.last ? `${t('hrt.last_dose')}: ${shortDate(parseIsoDate(view.last.date), lang)}` : t('hrt.course_idle')}
            </span>
          </div>
        </div>
      </Headline>

      <div className="grid hrt-grid">
        <div className="c7">
          {/* Active Cycle */}
          <Section title={t('hrt.active_cycle')}>
            {activeC ? (
              <div className="hrt-cycle-sec">
                <div className="hrt-cycle-head">
                  <div>
                    <Badge tone="violet">{t(`hrt.kind.${activeC.kind}`) || activeC.kind.toUpperCase()}</Badge>
                    <h3>{activeC.name || t(`hrt.kind.${activeC.kind}`) || activeC.kind}</h3>
                    <p className="sub">
                      {shortDate(parseIsoDate(activeC.start), lang)}
                      {activeC.end ? ` — ${shortDate(parseIsoDate(activeC.end), lang)}` : ''}
                    </p>
                  </div>
                  <TextButton onClick={handleCloseCycle}>
                    {t('hrt.close_cycle')}
                  </TextButton>
                </div>

                {/* Progress bar */}
                <div className="hrt-progress">
                  <div className="hrt-progress-head">
                    <span>{t('hrt.cycle_progress')}</span>
                    <b>
                      {activeC.weeks != null
                        ? t('hrt.week_of', { week: activeC.week, weeks: activeC.weeks })
                        : t('app.more.week', { week: activeC.week })}
                    </b>
                  </div>
                  {activeC.pct != null && (
                    <div className="hrt-meter">
                      <div
                        className="hrt-meter-fill"
                        style={{ transform: `scaleX(${Math.min(Math.max((activeC.pct ?? 0) / 100, 0), 1)})` }}
                      />
                    </div>
                  )}
                </div>

                {/* Release curve */}
                {releaseSvg && (
                  <div className="hrt-sparkline-wrap">
                    <div className="hrt-sparkline-head">
                      <span>{t('hrt.release_curve')}</span>
                      <span>{t('app.hrt.peak_mg', { val: releaseSvg.maxMg })}</span>
                    </div>
                    <svg viewBox="0 0 500 70" preserveAspectRatio="none" className="hrt-sparkline-svg">
                      <polyline fill="none" stroke="var(--violet)" strokeWidth="2.5" points={releaseSvg.points} />
                    </svg>
                  </div>
                )}

                {/* Planned compounds */}
                <div style={{ marginTop: '16px' }}>
                  <div className="sec-h" style={{ marginBottom: '8px' }}>
                    <span className="flabel" style={{ fontWeight: 600 }}>{t('hrt.planned_compounds')}</span>
                    <TextButton icon="plus" onClick={() => setItemModalOpen(true)}>
                      {t('hrt.add_item')}
                    </TextButton>
                  </div>
                  <div className="hrt-plan-list">
                    {activeC.items.map((it) => (
                      <div key={it.id} className="hrt-plan-row">
                        <div className="hrt-plan-info">
                          <span className="hrt-plan-name">{it.name}</span>
                          <span className="hrt-plan-sub">
                            {formatNumber(it.dose, lang, 1)} {t('app.unit.mg')}
                            {it.every != null ? ` · ${t('app.hrt.every_d', { days: it.every })}` : ''} · {t('app.hrt.week_plus', { week: it.from })}
                          </span>
                        </div>
                        <div className="hrt-plan-actions">
                          <button
                            type="button"
                            className="ibtn danger"
                            onClick={() => handleDeleteItem(it.id)}
                            aria-label={t('common.delete')}
                          >
                            <Icon name="x" />
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Save as template */}
                <div className="hrt-template-save-bar">
                  <input
                    className="input grow"
                    placeholder={t('hrt.template_name_placeholder')}
                    value={templateName}
                    onChange={(e) => setTemplateName(e.target.value)}
                  />
                  <TextButton onClick={handleSaveTemplate}>
                    {t('hrt.save_as_template')}
                  </TextButton>
                </div>
              </div>
            ) : (
              <div className="hrt-empty-box">
                <Icon name="pulse" />
                <p>{t('hrt.no_cycle_running')}</p>
                <div className="hrt-empty-acts">
                  <PrimaryButton onPress={async () => { setCycleModalOpen(true); return true }}>
                    {t('hrt.start_cycle')}
                  </PrimaryButton>
                </div>
              </div>
            )}
          </Section>

          {/* Dose Journal */}
          <Section
            title={t('hrt.dose_journal')}
            meta={t('app.hrt.logged_doses_count', { count: view.doses.length })}
          >
            <div className="rows">
              {view.doses.length === 0 ? (
                <div className="row">
                  <span className="m">{t('hrt.no_doses_logged')}</span>
                </div>
              ) : (
                view.doses.slice(0, 15).map((d) => (
                  <div key={d.id} className="row r-dose">
                    <div>
                      <div className="t">{d.name}</div>
                      <div className="m">
                        {shortDate(parseIsoDate(d.date), lang)}
                        {d.site ? ` · ${view.siteLabels[d.site] || d.site}` : ''}
                        {d.brand ? ` · ${d.brand}` : ''}
                      </div>
                    </div>
                    <div className="v">
                      {formatNumber(d.doseVal, lang, 1)}
                      <span className="u">{t('app.unit.mg')}</span>
                    </div>
                    <div className="acts">
                      <button
                        type="button"
                        className="ibtn danger"
                        onClick={() => handleDeleteDose(d.id)}
                        aria-label={t('common.delete')}
                      >
                        <Icon name="trash" />
                      </button>
                    </div>
                  </div>
                ))
              )}
            </div>
          </Section>
        </div>

        <div className="c5">
          {/* Side Effects */}
          <Section
            title={t('hrt.side_effects')}
            meta={
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <span className="meta">{t('app.hrt.logged_count', { count: view.sideEffects.length })}</span>
                <TextButton icon="plus" onClick={() => setSideEffectModalOpen(true)}>
                  {t('common.add')}
                </TextButton>
              </div>
            }
          >
            <div className="rows">
              {view.sideEffects.length === 0 ? (
                <div className="row">
                  <span className="m">{t('hrt.no_side_effects')}</span>
                </div>
              ) : (
                view.sideEffects.map((se) => {
                  const seName = t(`app.hrt.side.${se.name}`) || se.name
                  return (
                    <div key={se.id} className="row hrt-side-effect-item">
                      <div className="hrt-side-effect-info">
                        <span className="hrt-side-effect-name">{seName}</span>
                        <span className="hrt-side-effect-date">{shortDate(parseIsoDate(se.date), lang)}</span>
                      </div>
                      <div className="hrt-side-effect-acts">
                        <Delta tone={se.sev > 3 ? 'bad' : undefined}>
                          {t('app.hrt.grade_n', { grade: se.sev })}
                        </Delta>
                        <button
                          type="button"
                          className="ibtn danger"
                          onClick={() => handleDeleteSideEffect(se.id)}
                          aria-label={t('common.delete')}
                        >
                          <Icon name="x" />
                        </button>
                      </div>
                    </div>
                  )
                })
              )}
            </div>
          </Section>

          {/* Templates Library */}
          <Section title={t('hrt.templates')}>
            <div className="rows">
              {view.templates.length === 0 ? (
                <div className="row">
                  <span className="m">{t('hrt.no_templates')}</span>
                </div>
              ) : (
                view.templates.map((tpl) => (
                  <div key={tpl.id} className="row hrt-template-item">
                    <div className="hrt-template-info">
                      <span className="hrt-template-name">{tpl.name}</span>
                      <span className="hrt-template-sub">
                        {tpl.items.map(([c]) => c).join(', ')}
                      </span>
                    </div>
                    <TextButton onClick={() => handleApplyTemplate(tpl.id)}>
                      {t('hrt.apply_template')}
                    </TextButton>
                  </div>
                ))
              )}
            </div>
          </Section>
        </div>
      </div>

      {/* Modal: Log Dose */}
      {doseModalOpen && (
        <div className="hrt-form-modal">
          <div className="hrt-form-box">
            <div className="hrt-form-head">
              <h3 className="lab-modal-title">{t('hrt.add_dose')}</h3>
              <button type="button" className="ibtn" onClick={() => setDoseModalOpen(false)}>
                <Icon name="x" />
              </button>
            </div>
            <div className="hrt-form-body">
              <label className="field">
                <span className="flabel">{t('common.date')}</span>
                <input type="date" className="input" value={doseDate} onChange={(e) => setDoseDate(e.target.value)} />
              </label>
              <label className="field">
                <span className="flabel">{t('hrt.compound')}</span>
                <select className="input" value={doseCompound} onChange={(e) => setDoseCompound(e.target.value)}>
                  {view.compounds.map((c) => (
                    <option key={c.key} value={c.key}>{c.name}</option>
                  ))}
                </select>
              </label>
              <div className="hrt-form-grid2">
                <label className="field">
                  <span className="flabel">{t('hrt.dose')}</span>
                  <input type="number" step="0.1" className="input" value={doseVal} onChange={(e) => setDoseVal(e.target.value)} />
                </label>
                <label className="field">
                  <span className="flabel">{t('common.unit')}</span>
                  <input className="input" value={doseUnit} onChange={(e) => setDoseUnit(e.target.value)} />
                </label>
              </div>
              <label className="field">
                <span className="flabel">{t('hrt.site')}</span>
                <select className="input" value={doseSite} onChange={(e) => setDoseSite(e.target.value)}>
                  {Object.entries(view.siteLabels).map(([k, lbl]) => (
                    <option key={k} value={k}>{lbl}</option>
                  ))}
                </select>
              </label>
              <label className="field">
                <span className="flabel">{t('hrt.brand')}</span>
                <input className="input" value={doseBrand} onChange={(e) => setDoseBrand(e.target.value)} />
              </label>
              <label className="field">
                <span className="flabel">{t('common.note')}</span>
                <input className="input" value={doseNote} onChange={(e) => setDoseNote(e.target.value)} />
              </label>
              <ConflictAlert
                violations={doseConflict.violations}
                onFix={() => doseConflict.clearConflict()}
                onSaveAnyway={() => doseButtonRef.current?.press({ override: true })}
              />
              <PrimaryButton ref={doseButtonRef} className="btn grow" onPress={doseConflict.submit}>
                {t('common.save')}
              </PrimaryButton>
            </div>
          </div>
        </div>
      )}

      {/* Modal: Start Cycle */}
      {cycleModalOpen && (
        <div className="hrt-form-modal">
          <div className="hrt-form-box">
            <div className="hrt-form-head">
              <h3 className="lab-modal-title">{t('hrt.start_cycle')}</h3>
              <button type="button" className="ibtn" onClick={() => setCycleModalOpen(false)}>
                <Icon name="x" />
              </button>
            </div>
            <div className="hrt-form-body">
              <label className="field">
                <span className="flabel">{t('hrt.cycle_kind')}</span>
                <select className="input" value={cycleKind} onChange={(e) => setCycleKind(e.target.value)}>
                  <option value="trt">{t('hrt.kind.trt')}</option>
                  <option value="blast">{t('hrt.kind.blast')}</option>
                  <option value="cruise">{t('hrt.kind.cruise')}</option>
                  <option value="pct">{t('hrt.kind.pct')}</option>
                </select>
              </label>
              <label className="field">
                <span className="flabel">{t('hrt.cycle_name')}</span>
                <input className="input" placeholder="e.g. Spring 2026" value={cycleName} onChange={(e) => setCycleName(e.target.value)} />
              </label>
              <label className="field">
                <span className="flabel">{t('common.start_date')}</span>
                <input type="date" className="input" value={cycleStart} onChange={(e) => setCycleStart(e.target.value)} />
              </label>
              <label className="field">
                <span className="flabel">{t('common.end_date')}</span>
                <input type="date" className="input" value={cycleEnd} onChange={(e) => setCycleEnd(e.target.value)} />
              </label>
              <PrimaryButton className="btn grow" onPress={handleCreateCycle}>
                {t('hrt.start_cycle')}
              </PrimaryButton>
            </div>
          </div>
        </div>
      )}

      {/* Modal: Add Compound Item */}
      {itemModalOpen && (
        <div className="hrt-form-modal">
          <div className="hrt-form-box">
            <div className="hrt-form-head">
              <h3 className="lab-modal-title">{t('hrt.add_item')}</h3>
              <button type="button" className="ibtn" onClick={() => setItemModalOpen(false)}>
                <Icon name="x" />
              </button>
            </div>
            <div className="hrt-form-body">
              <label className="field">
                <span className="flabel">{t('hrt.compound')}</span>
                <select className="input" value={itemCompound} onChange={(e) => setItemCompound(e.target.value)}>
                  {view.compounds.map((c) => (
                    <option key={c.key} value={c.key}>{c.name}</option>
                  ))}
                </select>
              </label>
              <div className="hrt-form-grid2">
                <label className="field">
                  <span className="flabel">{t('hrt.dose')}</span>
                  <input type="number" step="0.5" className="input" value={itemDose} onChange={(e) => setItemDose(e.target.value)} />
                </label>
                <label className="field">
                  <span className="flabel">{t('hrt.interval_days')}</span>
                  <input type="number" step="0.5" className="input" value={itemInterval} onChange={(e) => setItemInterval(e.target.value)} />
                </label>
              </div>
              <label className="field">
                <span className="flabel">{t('hrt.start_week')}</span>
                <input type="number" min="1" className="input" value={itemStartWeek} onChange={(e) => setItemStartWeek(e.target.value)} />
              </label>
              <PrimaryButton className="btn grow" onPress={handleAddItem}>
                {t('common.save')}
              </PrimaryButton>
            </div>
          </div>
        </div>
      )}

      {/* Modal: Side Effect */}
      {sideEffectModalOpen && (
        <div className="hrt-form-modal">
          <div className="hrt-form-box">
            <div className="hrt-form-head">
              <h3 className="lab-modal-title">{t('hrt.log_side_effect')}</h3>
              <button type="button" className="ibtn" onClick={() => setSideEffectModalOpen(false)}>
                <Icon name="x" />
              </button>
            </div>
            <div className="hrt-form-body">
              <label className="field">
                <span className="flabel">{t('common.date')}</span>
                <input type="date" className="input" value={seDate} onChange={(e) => setSeDate(e.target.value)} />
              </label>
              <label className="field">
                <span className="flabel">{t('hrt.symptom')}</span>
                <input className="input" placeholder="e.g. acne, insomnia" value={seType} onChange={(e) => setSeType(e.target.value)} />
              </label>
              <label className="field">
                <span className="flabel">{t('hrt.severity_label')}</span>
                <input type="range" min="1" max="5" className="hrt-range-input" value={seSev} onChange={(e) => setSeSev(parseInt(e.target.value, 10))} />
                <span className="hrt-range-sub">{t('hrt.severity_level', { sev: seSev })}</span>
              </label>
              <label className="field">
                <span className="flabel">{t('common.note')}</span>
                <input className="input" value={seNote} onChange={(e) => setSeNote(e.target.value)} />
              </label>
              <PrimaryButton className="btn grow" onPress={handleCreateSideEffect}>
                {t('common.save')}
              </PrimaryButton>
            </div>
          </div>
        </div>
      )}
    </>
  )
}
