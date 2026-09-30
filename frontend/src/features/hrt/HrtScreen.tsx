import { useMemo, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { api, failText, InvalidError, ok } from '@/api/client'
import { ConfirmButton } from '@/components/controls/ConfirmButton'
import { ConflictAlert } from '@/components/controls/ConflictAlert'
import { Disclosure } from '@/components/controls/Disclosure'
import { DomainAlerts } from '@/components/controls/DomainAlerts'
import { Badge, Delta, TextButton } from '@/components/controls/Marks'
import { PrimaryButton, type PrimaryButtonHandle } from '@/components/controls/PrimaryButton'
import { Section } from '@/components/controls/Section'
import { toast } from '@/components/controls/toast'
import { Icon } from '@/components/icons/Icon'
import { Headline, Mast, TopBar } from '@/components/shell/PageHead'
import { useT } from '@/i18n/useT'
import { parseIsoDate, shortDate, toIsoDate } from '@/lib/dates'
import { formatCompact } from '@/lib/format'
import { useConflictMutation } from '@/lib/useConflictMutation'
import { buildDoseBody, buildItemBody, buildItemPatch, templateFileName } from './hrtBody'
import type { HrtCyclePlanItem, HrtDoseItem, HrtTemplateItem } from './types'
import { useHrtView } from './useHrtView'
import './hrt.css'

export default function HrtScreen() {
  const { t, tOr, lang } = useT()
  const view = useHrtView()
  const queryClient = useQueryClient()

  const [doseModalOpen, setDoseModalOpen] = useState(false)
  const [cycleModalOpen, setCycleModalOpen] = useState(false)
  const [itemModalOpen, setItemModalOpen] = useState(false)
  const [sideEffectModalOpen, setSideEffectModalOpen] = useState(false)
  const [templateName, setTemplateName] = useState('')
  // What the dose and the plan forms are correcting; `null` while they add a new entry.
  const [editingDoseId, setEditingDoseId] = useState<number | null>(null)
  const [editingItem, setEditingItem] = useState<HrtCyclePlanItem | null>(null)
  const [importOpen, setImportOpen] = useState(false)
  const [importPayload, setImportPayload] = useState('')
  const doseButtonRef = useRef<PrimaryButtonHandle>(null)

  // Form states
  const todayStr = useMemo(() => toIsoDate(new Date()), [])
  const [doseDate, setDoseDate] = useState(todayStr)
  const [doseCompound, setDoseCompound] = useState(() => view.compounds[0]?.key ?? 'testosterone_cypionate')
  const [doseVal, setDoseVal] = useState('')
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
  const [itemDose, setItemDose] = useState('')
  const [itemInterval, setItemInterval] = useState('')
  const [itemStartWeek, setItemStartWeek] = useState('')
  const [itemDuration, setItemDuration] = useState('')

  // Side effect form states
  const [seDate, setSeDate] = useState(todayStr)
  const [seType, setSeType] = useState('acne')
  const [seSev, setSeSev] = useState(2)
  const [seNote, setSeNote] = useState('')

  const activeC = view.cycle
  const doseBody = buildDoseBody({ dose: doseVal })
  const itemFields = { dose: itemDose, interval: itemInterval, startWeek: itemStartWeek, duration: itemDuration }
  const itemFlat = editingItem === null || editingItem.flat !== false
  const itemBody = buildItemBody(itemFields)
  const itemPatch = buildItemPatch({ ...itemFields, flat: itemFlat })

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ['hrt'] })
    void queryClient.invalidateQueries({ queryKey: ['today'] })
  }

  const openDoseAdd = () => {
    setEditingDoseId(null)
    setDoseModalOpen(true)
  }

  const openDoseEdit = (d: HrtDoseItem) => {
    setEditingDoseId(d.id)
    setDoseDate(d.date)
    setDoseCompound(d.compoundKey)
    setDoseVal(String(d.doseVal))
    setDoseUnit(d.unit)
    setDoseSite(d.site ?? '')
    setDoseBrand(d.brand ?? '')
    setDoseNote(d.note ?? '')
    setDoseModalOpen(true)
  }

  // A corrected entry must not become the starting point of the next new one.
  const closeDoseModal = () => {
    if (editingDoseId !== null) {
      setDoseDate(todayStr)
      setDoseVal('')
      setDoseBrand('')
      setDoseNote('')
    }
    setEditingDoseId(null)
    setDoseModalOpen(false)
    doseConflict.clearConflict()
  }

  // Dose submission
  const doseConflict = useConflictMutation({
    mutationFn: async ({ override }) => {
      if (doseBody === null) throw new InvalidError('')
      const body = {
        date: doseDate,
        compoundKey: doseCompound,
        ...doseBody,
        unit: doseUnit,
        site: doseSite || null,
        brand: doseBrand || null,
        note: doseNote || null,
        override,
      }
      const data =
        editingDoseId === null
          ? await ok(api.POST('/api/v1/hrt/doses', { body }))
          : await ok(api.PATCH('/api/v1/hrt/doses/{dose_id}', { params: { path: { dose_id: editingDoseId } }, body }))
      toast(t('common.saved'))
      closeDoseModal()
      refresh()
      return data
    },
    fallbackErrorMessage: t('app.save_failed'),
    onError: (err) => {
      toast(failText(err, t('app.save_failed')), { icon: 'warn' })
    },
  })

  // Delete dose
  const handleDeleteDose = async (id: number) => {
    try {
      await ok(api.DELETE('/api/v1/hrt/doses/{dose_id}', { params: { path: { dose_id: id } } }))
      toast(t('common.deleted'))
      refresh()
    } catch (err) {
      toast(failText(err, t('app.delete_failed')), { icon: 'warn' })
    }
  }

  // Cycle creation
  const handleCreateCycle = async (): Promise<boolean> => {
    try {
      await ok(
        api.POST('/api/v1/hrt/cycles', {
          body: {
            kind: cycleKind,
            name: cycleName || null,
            startDate: cycleStart,
            endDate: cycleEnd || null,
          },
        }),
      )
      toast(t('common.saved'))
      setCycleModalOpen(false)
      refresh()
      return true
    } catch (err) {
      toast(failText(err, t('app.save_failed')), { icon: 'warn' })
      return false
    }
  }

  // Close cycle
  const handleCloseCycle = async () => {
    if (!activeC) return
    try {
      await ok(api.POST('/api/v1/hrt/cycles/{cycle_id}/close', {
        params: { path: { cycle_id: activeC.id } },
        body: { endDate: todayStr },
      }))
      toast(t('hrt.cycle_closed'))
      refresh()
    } catch (err) {
      toast(failText(err, t('app.action_failed')), { icon: 'warn' })
    }
  }

  // Delete the cycle with its plan; the logged doses stay
  const handleDeleteCycle = async () => {
    if (!activeC) return
    try {
      await ok(api.DELETE('/api/v1/hrt/cycles/{cycle_id}', { params: { path: { cycle_id: activeC.id } } }))
      toast(t('common.deleted'))
      refresh()
    } catch (err) {
      toast(failText(err, t('app.delete_failed')), { icon: 'warn' })
    }
  }

  const openItemAdd = () => {
    setEditingItem(null)
    setItemModalOpen(true)
  }

  const openItemEdit = (it: HrtCyclePlanItem) => {
    setEditingItem(it)
    setItemCompound(it.compoundKey)
    setItemDose(it.flat === false ? '' : String(it.dose))
    setItemInterval(it.every == null ? '' : String(it.every))
    setItemStartWeek(String(it.from))
    setItemDuration(it.durationDays == null ? '' : String(it.durationDays))
    setItemModalOpen(true)
  }

  const closeItemModal = () => {
    if (editingItem !== null) {
      setItemDose('')
      setItemInterval('')
      setItemStartWeek('')
      setItemDuration('')
    }
    setEditingItem(null)
    setItemModalOpen(false)
  }

  // Add a compound to the cycle's plan, or correct one that is in it
  const handleSaveItem = async (): Promise<boolean> => {
    if (!activeC) return false
    try {
      if (editingItem !== null) {
        if (itemPatch === null) return false
        await ok(api.PATCH('/api/v1/hrt/cycle-items/{item_id}', { params: { path: { item_id: editingItem.id } }, body: itemPatch }))
      } else {
        if (itemBody === null) return false
        await ok(
          api.POST('/api/v1/hrt/cycles/{cycle_id}/items', {
            params: { path: { cycle_id: activeC.id } },
            body: {
              compoundKey: itemCompound,
              ...itemBody,
            },
          }),
        )
      }
      toast(t('common.saved'))
      closeItemModal()
      refresh()
      return true
    } catch (err) {
      toast(failText(err, t('app.save_failed')), { icon: 'warn' })
      return false
    }
  }

  // Delete compound item
  const handleDeleteItem = async (itemId: number) => {
    try {
      await ok(api.DELETE('/api/v1/hrt/cycle-items/{item_id}', { params: { path: { item_id: itemId } } }))
      toast(t('common.deleted'))
      refresh()
    } catch (err) {
      toast(failText(err, t('app.delete_failed')), { icon: 'warn' })
    }
  }

  // Save active cycle as template
  const handleSaveTemplate = async () => {
    if (!activeC || !templateName.trim()) return
    try {
      await ok(api.POST('/api/v1/hrt/cycles/{cycle_id}/save-template', {
        params: { path: { cycle_id: activeC.id } },
        body: { name: templateName.trim() },
      }))
      toast(t('hrt.template_saved'))
      setTemplateName('')
      refresh()
    } catch (err) {
      toast(failText(err, t('app.save_failed')), { icon: 'warn' })
    }
  }

  // Apply template to start cycle
  const handleApplyTemplate = async (templateId: number) => {
    try {
      await ok(api.POST('/api/v1/hrt/templates/{template_id}/create-cycle', {
        params: { path: { template_id: templateId } },
        body: { startDate: todayStr },
      }))
      toast(t('hrt.cycle_started'))
      refresh()
    } catch (err) {
      toast(failText(err, t('app.action_failed')), { icon: 'warn' })
    }
  }

  const handleDeleteTemplate = async (templateId: number) => {
    try {
      await ok(api.DELETE('/api/v1/hrt/templates/{template_id}', { params: { path: { template_id: templateId } } }))
      toast(t('common.deleted'))
      refresh()
    } catch (err) {
      toast(failText(err, t('app.delete_failed')), { icon: 'warn' })
    }
  }

  // The share payload goes to the clipboard; where that is not allowed, it is saved as a file.
  // It is already on the screen's data, so the copy happens inside the tap that asked for it.
  const handleExportTemplate = async (tpl: HrtTemplateItem) => {
    try {
      await navigator.clipboard.writeText(tpl.exportJson)
      toast(t('hrt.copied'))
    } catch {
      const url = URL.createObjectURL(new Blob([tpl.exportJson], { type: 'application/json' }))
      const a = document.createElement('a')
      a.href = url
      a.download = templateFileName(tpl.name)
      document.body.appendChild(a)
      a.click()
      a.remove()
      URL.revokeObjectURL(url)
      toast(t('app.hrt.template_downloaded'))
    }
  }

  const handleImportTemplate = async () => {
    try {
      await ok(api.POST('/api/v1/hrt/templates/import', { body: { payload: importPayload } }))
      toast(t('app.hrt.template_imported'))
      setImportPayload('')
      setImportOpen(false)
      refresh()
    } catch (err) {
      // The service names what is wrong with the payload, in its own words.
      toast(err instanceof InvalidError ? t('app.hrt.import_invalid', { reason: err.message }) : t('app.save_failed'), { icon: 'warn' })
    }
  }

  // Side effect log
  const handleCreateSideEffect = async (): Promise<boolean> => {
    try {
      await ok(api.POST('/api/v1/hrt/side-effects', {
        body: {
          date: seDate,
          effectType: seType,
          severity: seSev,
          note: seNote || null,
        },
      }))
      toast(t('common.saved'))
      setSideEffectModalOpen(false)
      refresh()
      return true
    } catch (err) {
      toast(failText(err, t('app.save_failed')), { icon: 'warn' })
      return false
    }
  }

  // Delete side effect
  const handleDeleteSideEffect = async (id: number) => {
    try {
      await ok(api.DELETE('/api/v1/hrt/side-effects/{effect_id}', { params: { path: { effect_id: id } } }))
      toast(t('common.deleted'))
      refresh()
    } catch (err) {
      toast(failText(err, t('app.delete_failed')), { icon: 'warn' })
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
    return { points: coords.join(' '), maxMg: formatCompact(maxMg, lang, 1) }
  }, [view.release, lang])

  const lastDoseVal = view.last ? parseFloat(view.last.dose) : NaN
  const lastDoseNum = !Number.isNaN(lastDoseVal) ? formatCompact(lastDoseVal, lang, 2) : (view.last?.dose ?? '—')

  return (
    <>
      <TopBar title={t('nav.hrt')} />
      <Mast
        screen="hrt"
        actions={
          <div className="hrt-acts">
            <TextButton icon="syringe" onClick={openDoseAdd}>
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
      <DomainAlerts domain="hrt" />

      <div className="grid hrt-grid">
        <div className="c7">
          {/* Active Cycle */}
          <Section title={t('hrt.active_cycle')}>
            {activeC ? (
              <div className="hrt-cycle-sec">
                <div className="hrt-cycle-head">
                  <div>
                    <Badge tone="violet">{tOr(`hrt.kind.${activeC.kind}`, activeC.kind.toUpperCase())}</Badge>
                    <h3>{activeC.name || tOr(`hrt.kind.${activeC.kind}`, activeC.kind)}</h3>
                    <p className="sub">
                      {shortDate(parseIsoDate(activeC.start), lang)}
                      {activeC.end ? ` — ${shortDate(parseIsoDate(activeC.end), lang)}` : ''}
                    </p>
                  </div>
                  <div className="hrt-acts">
                    <TextButton onClick={handleCloseCycle}>
                      {t('hrt.close_cycle')}
                    </TextButton>
                    <ConfirmButton text label={t('hrt.delete_cycle')} onConfirm={() => void handleDeleteCycle()} />
                  </div>
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
                    <TextButton icon="plus" onClick={openItemAdd}>
                      {t('hrt.add_item')}
                    </TextButton>
                  </div>
                  <div className="hrt-plan-list">
                    {activeC.items.map((it) => (
                      <div key={it.id} className="hrt-plan-row">
                        <div className="hrt-plan-info">
                          <span className="hrt-plan-name">{it.name}</span>
                          <span className="hrt-plan-sub">
                            {formatCompact(it.dose, lang, 2)} {t('app.unit.mg')}
                            {it.every != null ? ` · ${t('app.hrt.every_d', { days: formatCompact(it.every, lang, 2) })}` : ''} · {t('app.hrt.week_plus', { week: it.from })}
                          </span>
                        </div>
                        <div className="hrt-plan-actions">
                          <button type="button" className="ibtn" onClick={() => openItemEdit(it)} aria-label={t('common.edit')} title={t('common.edit')}>
                            <Icon name="edit" />
                          </button>
                          <ConfirmButton label={t('common.delete')} onConfirm={() => void handleDeleteItem(it.id)} />
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
                      {formatCompact(d.doseVal, lang, 2)}
                      <span className="u">{t('app.unit.mg')}</span>
                    </div>
                    <div className="acts">
                      <button type="button" className="ibtn" onClick={() => openDoseEdit(d)} aria-label={t('common.edit')} title={t('common.edit')}>
                        <Icon name="edit" />
                      </button>
                      <ConfirmButton label={t('common.delete')} onConfirm={() => void handleDeleteDose(d.id)} />
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
                  const seName = tOr(`app.hrt.side.${se.name}`, se.name)
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
                        <ConfirmButton label={t('common.delete')} onConfirm={() => void handleDeleteSideEffect(se.id)} />
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
                    <div className="acts">
                      <TextButton onClick={() => handleApplyTemplate(tpl.id)}>
                        {t('hrt.apply_template')}
                      </TextButton>
                      <button type="button" className="ibtn" onClick={() => void handleExportTemplate(tpl)} aria-label={t('hrt.export')} title={t('hrt.export')}>
                        <Icon name="copy" />
                      </button>
                      <ConfirmButton label={t('hrt.delete')} onConfirm={() => void handleDeleteTemplate(tpl.id)} />
                    </div>
                  </div>
                ))
              )}
              <Disclosure open={importOpen} onToggle={() => setImportOpen(!importOpen)} title={t('hrt.import_template')}>
                <div className="disc-body hrt-import">
                  <textarea
                    className="input mono"
                    rows={6}
                    aria-label={t('hrt.import_template')}
                    placeholder={'{"format": "vitals.hrt_cycle_template", …}'}
                    value={importPayload}
                    onChange={(e) => setImportPayload(e.target.value)}
                  />
                  <TextButton icon="upload" disabled={importPayload.trim() === ''} onClick={() => void handleImportTemplate()}>
                    {t('hrt.import_btn')}
                  </TextButton>
                </div>
              </Disclosure>
            </div>
          </Section>
        </div>
      </div>

      {/* Modal: Log Dose */}
      {doseModalOpen && (
        <div className="hrt-form-modal">
          <div className="hrt-form-box">
            <div className="hrt-form-head">
              <h3 className="lab-modal-title">{editingDoseId === null ? t('hrt.add_dose') : t('app.hrt.edit_dose')}</h3>
              <button type="button" className="ibtn" aria-label={t('app.close')} onClick={closeDoseModal}>
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
                  <option value="">—</option>
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
              <PrimaryButton ref={doseButtonRef} className="btn grow" disabled={doseBody === null} onPress={doseConflict.submit}>
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
                <input className="input" placeholder={t('hrt.cycle_name_ph')} value={cycleName} onChange={(e) => setCycleName(e.target.value)} />
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
              <h3 className="lab-modal-title">{editingItem === null ? t('hrt.add_item') : t('app.hrt.edit_item')}</h3>
              <button type="button" className="ibtn" aria-label={t('app.close')} onClick={closeItemModal}>
                <Icon name="x" />
              </button>
            </div>
            <div className="hrt-form-body">
              <label className="field">
                <span className="flabel">{t('hrt.compound')}</span>
                <select className="input" value={itemCompound} disabled={editingItem !== null} onChange={(e) => setItemCompound(e.target.value)}>
                  {view.compounds.map((c) => (
                    <option key={c.key} value={c.key}>{c.name}</option>
                  ))}
                </select>
              </label>
              {itemFlat ? (
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
              ) : (
                <p className="sub flush">{t('hrt.item_complex_note')}</p>
              )}
              <div className="hrt-form-grid2">
                <label className="field">
                  <span className="flabel">{t('hrt.start_week')}</span>
                  <input type="number" min="1" className="input" value={itemStartWeek} onChange={(e) => setItemStartWeek(e.target.value)} />
                </label>
                {itemFlat ? (
                  <label className="field">
                    <span className="flabel">{t('hrt.duration_days')}</span>
                    <input type="number" min="1" step="1" className="input" value={itemDuration} onChange={(e) => setItemDuration(e.target.value)} />
                  </label>
                ) : null}
              </div>
              <PrimaryButton className="btn grow" disabled={(editingItem === null ? itemBody : itemPatch) === null} onPress={handleSaveItem}>
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
                <input className="input" placeholder={t('hrt.symptom_ph')} value={seType} onChange={(e) => setSeType(e.target.value)} />
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
