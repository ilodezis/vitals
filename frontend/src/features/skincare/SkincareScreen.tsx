import { useMemo, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { api, ok, failText } from '@/api/client'
import { ConflictAlert } from '@/components/controls/ConflictAlert'
import { Disclosure } from '@/components/controls/Disclosure'
import { Badge } from '@/components/controls/Marks'
import { PrimaryButton, type PrimaryButtonHandle } from '@/components/controls/PrimaryButton'
import { toast } from '@/components/controls/toast'
import { Icon } from '@/components/icons/Icon'
import { DomainAlerts } from '@/components/controls/DomainAlerts'
import { Headline, Mast, TopBar } from '@/components/shell/PageHead'
import { useT } from '@/i18n/useT'
import { longDate, parseIsoDate, shortDate } from '@/lib/dates'
import { useConflictMutation } from '@/lib/useConflictMutation'
import { buildObservationScores } from './observationBody'
import type { SkincareProductItem, SkincareRuleItem } from './types'
import { useSkincareView } from './useSkincareView'
import './skincare.css'

const DOW_KEYS: [number, string][] = [
  [1, 'mon'],
  [2, 'tue'],
  [3, 'wed'],
  [4, 'thu'],
  [5, 'fri'],
  [6, 'sat'],
  [0, 'sun'],
]

export default function SkincareScreen() {
  const { t, tOr, lang } = useT()
  const view = useSkincareView()
  const queryClient = useQueryClient()

  const [formOpen, setFormOpen] = useState(false)
  const [editingProduct, setEditingProduct] = useState<SkincareProductItem | null>(null)
  // "Today" is the server's date (the user's timezone), not the browser's.
  const todayDow = parseIsoDate(view.today).getDay()
  const [selectedDay, setSelectedDay] = useState(todayDow)

  // Product form states
  const [name, setName] = useState('')
  const [type, setType] = useState('')
  const [activeIngredient, setActiveIngredient] = useState('')
  const [defaultTime, setDefaultTime] = useState('evening')
  const [scheduleDays, setScheduleDays] = useState<number[]>([1, 3, 5])
  const [description, setDescription] = useState('')
  const [usageInstructions, setUsageInstructions] = useState('')
  const [active, setActive] = useState(true)
  const [isSubmitting, setIsSubmitting] = useState(false)

  // Log today dialog states
  const [logOpen, setLogOpen] = useState(false)
  const [retinoid, setRetinoid] = useState(false)
  const [azelaic, setAzelaic] = useState(false)
  const [peel, setPeel] = useState(false)
  const [niacinamideSpf, setNiacinamideSpf] = useState(false)
  const [moisturizer, setMoisturizer] = useState(true)
  const [vitaminC, setVitaminC] = useState(false)
  const [logNote, setLogNote] = useState('')
  const logButtonRef = useRef<PrimaryButtonHandle>(null)

  // Observation dialog states
  const [obsOpen, setObsOpen] = useState(false)
  const [obsInf, setObsInf] = useState('')
  const [obsPih, setObsPih] = useState('')
  const [obsZone, setObsZone] = useState('chin')
  const [obsNote, setObsNote] = useState('')

  // Safety rules catalog collapse state
  const [openCats, setOpenCats] = useState<Set<string>>(() => new Set())

  const toggleCat = (cat: string) => {
    setOpenCats((prev) => {
      const next = new Set(prev)
      if (next.has(cat)) next.delete(cat)
      else next.add(cat)
      return next
    })
  }

  const activeProducts = useMemo(
    () => view.products.filter((p) => p.active || p.on),
    [view.products]
  )

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ['skincare'] })
    void queryClient.invalidateQueries({ queryKey: ['today'] })
  }

  const openCreateProduct = () => {
    setEditingProduct(null)
    setName('')
    setType(t('app.skincare.act.retinoid'))
    setActiveIngredient('')
    setDefaultTime('evening')
    setScheduleDays([1, 3, 5])
    setDescription('')
    setUsageInstructions('')
    setActive(true)
    setFormOpen(true)
  }

  const openEditProduct = (p: SkincareProductItem) => {
    setEditingProduct(p)
    setName(p.name)
    setType(p.type)
    setActiveIngredient(p.activeIngredient || p.ing || '')
    setDefaultTime(p.defaultTime || p.default_time || p.time || 'evening')
    setScheduleDays(p.scheduleDays || p.schedule_days || p.days || [])
    setDescription(p.description || p.desc || '')
    setUsageInstructions(p.usageInstructions || p.usage_instructions || p.use || '')
    setActive(p.active || p.on)
    setFormOpen(true)
  }

  const toggleDay = (d: number) => {
    setScheduleDays((prev) =>
      prev.includes(d) ? prev.filter((x) => x !== d) : [...prev, d].sort((a, b) => a - b)
    )
  }

  const handleSaveProduct = async (): Promise<boolean> => {
    if (!name.trim()) {
      toast(t('app.name_required'), { icon: 'warn' })
      return false
    }
    setIsSubmitting(true)
    try {
      if (editingProduct) {
        await ok(api.PATCH('/api/v1/skincare/products/{product_id}', {
          params: { path: { product_id: editingProduct.id } },
          body: {
            name: name.trim(),
            type: type.trim() || t('app.skincare.type_default'),
            activeIngredient: activeIngredient.trim() || null,
            defaultTime,
            scheduleDays,
            description: description.trim() || null,
            usageInstructions: usageInstructions.trim() || null,
            active,
          },
        }))
      } else {
        await ok(api.POST('/api/v1/skincare/products', {
          body: {
            name: name.trim(),
            type: type.trim() || t('app.skincare.type_default'),
            activeIngredient: activeIngredient.trim() || null,
            defaultTime,
            scheduleDays,
            description: description.trim() || null,
            usageInstructions: usageInstructions.trim() || null,
            active,
          },
        }))
      }
      toast(t('common.saved'))
      setFormOpen(false)
      refresh()
      return true
    } catch (err) {
      toast(failText(err, t('app.save_failed')), { icon: 'warn' })
      return false
    } finally {
      setIsSubmitting(false)
    }
  }

  const handleDeleteProduct = async (id: number) => {
    try {
      await ok(api.DELETE('/api/v1/skincare/products/{product_id}', {
        params: { path: { product_id: id } },
      }))
      toast(t('common.deleted'))
      refresh()
    } catch (err) {
      toast(failText(err, t('app.delete_failed')), { icon: 'warn' })
    }
  }

  const logConflict = useConflictMutation({
    mutationFn: async ({ override }) => {
      const data = await ok(
        api.POST('/api/v1/skincare/logs', {
          body: {
            date: view.today,
            retinoid,
            azelaic,
            peel,
            niacinamideSpf,
            moisturizer,
            vitaminC,
            benzoylPeroxide: false,
            note: logNote.trim() || null,
            override,
          },
        }),
      )
      toast(t('app.skincare.toast_saved'))
      setLogOpen(false)
      setLogNote('')
      refresh()
      return data
    },
    fallbackErrorMessage: t('app.save_failed'),
    onError: (err) => {
      toast(failText(err, t('app.save_failed')), { icon: 'warn' })
    },
  })

  const obsScores = buildObservationScores({ inflammation: obsInf, pih: obsPih })

  const handleSaveObservation = async (): Promise<boolean> => {
    if (obsScores === null) return false
    try {
      await ok(api.POST('/api/v1/skincare/observations', {
        body: {
          date: view.today,
          ...obsScores,
          zone: obsZone,
          note: obsNote.trim() || null,
        },
      }))
      toast(t('app.skincare.toast_obs_saved'))
      setObsOpen(false)
      setObsNote('')
      refresh()
      return true
    } catch (err) {
      toast(failText(err, t('app.save_failed')), { icon: 'warn' })
      return false
    }
  }

  const handleDeleteLog = async (id: number) => {
    try {
      await ok(api.DELETE('/api/v1/skincare/logs/{log_id}', {
        params: { path: { log_id: id } },
      }))
      toast(t('common.deleted'))
      refresh()
    } catch (err) {
      toast(failText(err, t('app.delete_failed')), { icon: 'warn' })
    }
  }

  const handleDeleteObservation = async (id: number) => {
    try {
      await ok(
        api.DELETE('/api/v1/skincare/observations/{obs_id}', {
          params: { path: { obs_id: id } },
        }),
      )
      toast(t('common.deleted'))
      refresh()
    } catch (err) {
      toast(failText(err, t('app.delete_failed')), { icon: 'warn' })
    }
  }

  const getProdsForCell = (dow: number, timeSlot: string) => {
    return activeProducts.filter((p) => {
      const pDays = p.scheduleDays || p.schedule_days || p.days || []
      const pTime = p.defaultTime || p.default_time || p.time || 'evening'
      const matchDay = pDays.includes(dow)
      const matchTime = pTime === 'both' || pTime === timeSlot
      return matchDay && matchTime
    })
  }

  // Firing rules & grouped catalog
  const firingRules = useMemo(() => {
    const alertKeys = new Set(view.alerts?.map((a) => a.alertKey || (a as any).alert_key) || [])
    return view.rules.filter((r) => (r as any).firing || (r.code && alertKeys.has(r.code)))
  }, [view.rules, view.alerts])

  const groupedRules = useMemo(() => {
    const map = new Map<string, SkincareRuleItem[]>()
    for (const r of view.rules) {
      const cat = r.kind || (r as any).category || 'dermatology'
      if (!map.has(cat)) map.set(cat, [])
      map.get(cat)!.push(r)
    }
    return map
  }, [view.rules])

  return (
    <>
      <TopBar
        title={t('nav.skincare')}
        right={
          <button type="button" className="ibtn" onClick={openCreateProduct} aria-label={t('app.skincare.add_product')}>
            <Icon name="plus" />
          </button>
        }
      />
      <Mast
        screen="skincare"
        actions={
          <button type="button" className="ghost" onClick={openCreateProduct}>
            <Icon name="plus" />
            <span>{t('app.skincare.add_product')}</span>
          </button>
        }
      />
      <Headline title={t('nav.skincare')}>
        <div className="figs inline">
          <div className="f">
            <div className="f-v">{view.activeCount}</div>
            <div className="f-l">{t('app.skincare.active_count')}</div>
          </div>
          <div className="f">
            <div className="f-v">{view.totalCount}</div>
            <div className="f-l">{t('app.skincare.total_count')}</div>
          </div>
        </div>
      </Headline>
      <DomainAlerts domain="skincare" />

      {/* Product Form Modal */}
      {formOpen && (
        <div className="panel fpanel" style={{ marginTop: 'var(--s6)' }}>
          <div className="panel-h">
            <h3>{editingProduct ? t('app.skincare.edit_product') : t('app.skincare.new_product')}</h3>
            <button type="button" className="ibtn" onClick={() => setFormOpen(false)}>
              <Icon name="x" />
            </button>
          </div>
          <div className="form sk-form">
            <label className="field">
              <span className="flabel">{t('app.skincare.product_name')}</span>
              <input
                className="input"
                placeholder={t('app.skincare.product_name_ph')}
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            </label>
            <div className="sk-grid-2">
              <label className="field">
                <span className="flabel">{t('app.skincare.product_type')}</span>
                <input
                  className="input"
                  placeholder={t('app.skincare.product_type_ph')}
                  value={type}
                  onChange={(e) => setType(e.target.value)}
                />
              </label>
              <label className="field">
                <span className="flabel">{t('app.skincare.active_ing')}</span>
                <input
                  className="input"
                  placeholder={t('app.skincare.active_ing_ph')}
                  value={activeIngredient}
                  onChange={(e) => setActiveIngredient(e.target.value)}
                />
              </label>
            </div>
            <label className="field">
              <span className="flabel">{t('app.skincare.apply_time')}</span>
              <select
                className="input"
                value={defaultTime}
                onChange={(e) => setDefaultTime(e.target.value)}
              >
                <option value="morning">{t('app.skincare.morning')}</option>
                <option value="evening">{t('app.skincare.evening')}</option>
                <option value="both">{t('app.skincare.both')}</option>
              </select>
            </label>
            <label className="field">
              <span className="flabel">{t('app.skincare.schedule_days')}</span>
              <div className="opts sk-opts">
                {DOW_KEYS.map(([d, k]) => (
                  <button
                    key={d}
                    type="button"
                    className={`opt ${scheduleDays.includes(d) ? 'on' : ''}`}
                    onClick={() => toggleDay(d)}
                  >
                    {t(`proactive.day.${k}`)}
                  </button>
                ))}
              </div>
            </label>
            <label className="field">
              <span className="flabel">{t('app.skincare.description')}</span>
              <textarea
                className="input"
                rows={2}
                placeholder="..."
                value={description}
                onChange={(e) => setDescription(e.target.value)}
              />
            </label>
            <label className="field">
              <span className="flabel">{t('app.skincare.instructions')}</span>
              <textarea
                className="input"
                rows={2}
                placeholder="..."
                value={usageInstructions}
                onChange={(e) => setUsageInstructions(e.target.value)}
              />
            </label>
            <div className="form-acts sk-form-acts">
              <PrimaryButton
                className="btn grow"
                onPress={handleSaveProduct}
                disabled={isSubmitting}
              >
                {t('common.save')}
              </PrimaryButton>
              <button
                type="button"
                className="ghost"
                onClick={() => setFormOpen(false)}
              >
                {t('common.cancel')}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Schedule Table (desktop) & Day Picker (mobile) */}
      <section className="sec">
        <div className="sec-h">
          <h2>{t('app.skincare.schedule_title')}</h2>
          <span className="meta">{t('app.skincare.schedule_sub')}</span>
        </div>

        {/* Desktop Table */}
        <div className="sched">
          <table>
            <thead>
              <tr>
                <th />
                {DOW_KEYS.map(([d, k]) => (
                  <th key={d} className={d === todayDow ? 'now' : ''}>
                    {t(`proactive.day.${k}`)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              <tr>
                <td className="lbl">
                  <Icon name="today" />
                  {t('app.skincare.morning')}
                </td>
                {DOW_KEYS.map(([d]) => {
                  const prods = getProdsForCell(d, 'morning')
                  return (
                    <td key={d} className={d === todayDow ? 'now' : ''}>
                      {prods.length ? (
                        prods.map((p) => (
                          <div key={p.id} className="pn">
                            {p.name}
                          </div>
                        ))
                      ) : (
                        <span className="m">—</span>
                      )}
                    </td>
                  )
                })}
              </tr>
              <tr>
                <td className="lbl">
                  <Icon name="pulse" />
                  {t('app.skincare.evening')}
                </td>
                {DOW_KEYS.map(([d]) => {
                  const prods = getProdsForCell(d, 'evening')
                  return (
                    <td key={d} className={d === todayDow ? 'now' : ''}>
                      {prods.length ? (
                        prods.map((p) => (
                          <div key={p.id} className="pn">
                            {p.name}
                          </div>
                        ))
                      ) : (
                        <span className="m">—</span>
                      )}
                    </td>
                  )
                })}
              </tr>
            </tbody>
          </table>
        </div>

        {/* Mobile Day Picker */}
        <div className="sched-m">
          <div className="opts sk-opts">
            {DOW_KEYS.map(([d, k]) => (
              <button
                key={d}
                type="button"
                className={`opt ${d === selectedDay ? 'on' : ''} ${d === todayDow ? 'today' : ''}`}
                onClick={() => setSelectedDay(d)}
              >
                {t(`proactive.day.${k}`)}
              </button>
            ))}
          </div>
          <div className="day-pane">
            <div className="row" style={{ gridTemplateColumns: '22px 1fr' }}>
              <span className="mi">
                <Icon name="today" />
              </span>
              <div>
                <div className="t">{t('app.skincare.morning')}</div>
                <div className="m">
                  {getProdsForCell(selectedDay, 'morning')
                    .map((p) => p.name)
                    .join(' · ') || '—'}
                </div>
              </div>
            </div>
            <div className="row" style={{ gridTemplateColumns: '22px 1fr' }}>
              <span className="mi">
                <Icon name="pulse" />
              </span>
              <div>
                <div className="t">{t('app.skincare.evening')}</div>
                <div className="m">
                  {getProdsForCell(selectedDay, 'evening')
                    .map((p) => p.name)
                    .join(' · ') || '—'}
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Grid: Products & Safety Rules */}
      <div className="grid sk-sec-grid">
        <div className="c7">
          <section className="sec o1">
            <div className="sec-h">
              <h2>{t('app.skincare.active_components')}</h2>
              <span className="meta">{t('app.skincare.components_sub')}</span>
            </div>
            <div className="prods">
              {view.products.map((p) => {
                const pDays = p.scheduleDays || p.schedule_days || p.days || []
                const pTime = p.defaultTime || p.default_time || p.time || 'evening'
                const timeLabel = pTime === 'morning' ? t('app.skincare.morning') : pTime === 'both' ? t('app.skincare.both') : t('app.skincare.evening')
                const timeTone = pTime === 'morning' ? 'cool' : pTime === 'both' ? 'good' : 'violet'
                const ingText = p.activeIngredient || p.ing
                const descText = p.description || p.desc
                const useText = p.usageInstructions || p.usage_instructions || p.use
                return (
                  <div key={p.id} className="prod" data-item>
                    <div className="row prod-h" style={{ gridTemplateColumns: 'minmax(0,1fr) auto' }}>
                      <div>
                        <div className="t">{p.name}</div>
                        {ingText && <div className="m">{t('app.skincare.active_label')} {ingText}</div>}
                      </div>
                      <span className="acts">
                        <button
                          type="button"
                          className="ibtn"
                          onClick={() => openEditProduct(p)}
                          aria-label={t('common.edit')}
                        >
                          <Icon name="edit" />
                        </button>
                        <button
                          type="button"
                          className="ibtn"
                          onClick={() => handleDeleteProduct(p.id)}
                          aria-label={t('common.delete')}
                        >
                          <Icon name="trash" />
                        </button>
                      </span>
                    </div>
                    <div className="prod-b">
                      <div className="prod-tags">
                        <Badge tone="plain">{p.type}</Badge>
                        <Badge tone={timeTone}>{timeLabel}</Badge>
                        <span className="m">
                          {t('app.skincare.days_label')}{' '}
                          {pDays.length
                            ? DOW_KEYS.filter(([d]) => pDays.includes(d))
                                .map(([, k]) => t(`proactive.day.${k}`))
                                .join(', ')
                            : t('app.skincare.days_none')}
                        </span>
                      </div>
                      {descText && <p className="prod-d">{descText}</p>}
                      {useText && (
                        <p className="m use">
                          <Icon name="doc" />
                          <span>{useText}</span>
                        </p>
                      )}
                    </div>
                  </div>
                )
              })}
            </div>
          </section>
        </div>

        <div className="c5">
          <section className="sec o2">
            <div className="sec-h">
              <h2>{t('app.skincare.safety_rules')}</h2>
              <span className="meta">{t('app.skincare.safety_sub')}</span>
            </div>
            <div className="alerts">
              {firingRules.length > 0 ? (
                firingRules.map((r) => (
                  <div
                    key={r.id}
                    className={`alert ${r.severity === 'block' || r.sev === 'block' ? 'block' : 'warn'}`}
                  >
                    <Icon name={r.hard ? 'block' : 'warn'} />
                    <div>
                      <b>{tOr(`app.rule_cat.${r.kind}`, r.kind)}</b>
                      <br />
                      {r.msg}
                    </div>
                  </div>
                ))
              ) : (
                <div className="sk-no-alerts">{t('app.skincare.no_firing')}</div>
              )}
            </div>

            {/* Catalog as Collapsed Categories */}
            <div className="sk-cat-list" style={{ marginTop: 'var(--s3)' }}>
              {Array.from(groupedRules.entries()).map(([cat, rules]) => {
                const isOpen = openCats.has(cat)
                const catLabel = tOr(`app.rule_cat.${cat}`, cat)
                return (
                  <Disclosure key={cat} open={isOpen} onToggle={() => toggleCat(cat)} title={catLabel} count={rules.length}>
                    <div className="rows">
                      {rules.map((r) => (
                        <div key={r.id} className="row sk-rule-row">
                          <div className="sk-rule-main">
                            <div className="t">{r.msg}</div>
                            <div className="m">
                              {r.code || (r.hard ? t('app.severity.block') : t('app.severity.warn'))}
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  </Disclosure>
                )
              })}
            </div>

            <div className="alert info" style={{ marginTop: 'var(--s4)' }}>
              <Icon name="drop" />
              <div>
                <b>{t('app.skincare.barrier_note_title')}</b>
                <br />
                {t('app.skincare.barrier_note_body')}
              </div>
            </div>
          </section>
        </div>
      </div>

      {/* Grid: Care Logs & Observations */}
      <div className="grid sk-sec-grid">
        <div className="c7">
          <section className="sec o3">
            <div className="sec-h">
              <h2>{t('app.skincare.diary_title')}</h2>
              <button
                type="button"
                className="ghost"
                onClick={() => setLogOpen(true)}
              >
                <Icon name="plus" />
                <span>{t('app.skincare.log_care')}</span>
              </button>
            </div>
            {logOpen && (
              <div className="panel fpanel mb-s4">
                <div className="panel-h">
                  <h3>{t('app.skincare.applied_today', { date: longDate(parseIsoDate(view.today), lang) })}</h3>
                  <button type="button" className="ibtn" onClick={() => setLogOpen(false)}>
                    <Icon name="x" />
                  </button>
                </div>
                <div className="sk-log-box">
                  <div className="opts sk-opts-gap2">
                    <button
                      type="button"
                      className={`opt ${retinoid ? 'on' : ''}`}
                      onClick={() => setRetinoid(!retinoid)}
                    >
                      {t('app.skincare.act.retinoid')}
                    </button>
                    <button
                      type="button"
                      className={`opt ${azelaic ? 'on' : ''}`}
                      onClick={() => setAzelaic(!azelaic)}
                    >
                      {t('app.skincare.act.azelaic')}
                    </button>
                    <button
                      type="button"
                      className={`opt ${peel ? 'on' : ''}`}
                      onClick={() => setPeel(!peel)}
                    >
                      {t('app.skincare.act.peel')}
                    </button>
                    <button
                      type="button"
                      className={`opt ${niacinamideSpf ? 'on' : ''}`}
                      onClick={() => setNiacinamideSpf(!niacinamideSpf)}
                    >
                      {t('app.skincare.act.niacinamide_spf')}
                    </button>
                    <button
                      type="button"
                      className={`opt ${moisturizer ? 'on' : ''}`}
                      onClick={() => setMoisturizer(!moisturizer)}
                    >
                      {t('app.skincare.act.moisturizer')}
                    </button>
                    <button
                      type="button"
                      className={`opt ${vitaminC ? 'on' : ''}`}
                      onClick={() => setVitaminC(!vitaminC)}
                    >
                      {t('app.skincare.act.vitamin_c')}
                    </button>
                  </div>
                  <input
                    className="input"
                    placeholder={t('app.skincare.note_ph')}
                    value={logNote}
                    onChange={(e) => setLogNote(e.target.value)}
                  />
                  <ConflictAlert
                    violations={logConflict.violations}
                    onFix={() => logConflict.clearConflict()}
                    onSaveAnyway={() => logButtonRef.current?.press({ override: true })}
                  />
                  <div className="form-acts sk-form-acts">
                    <PrimaryButton ref={logButtonRef} className="btn grow" onPress={logConflict.submit}>
                      {t('common.save')}
                    </PrimaryButton>
                    <button
                      type="button"
                      className="ghost"
                      onClick={() => setLogOpen(false)}
                    >
                      {t('common.cancel')}
                    </button>
                  </div>
                </div>
              </div>
            )}
            <div className="rows">
              {view.logs.map((l) => {
                const actives: string[] = []
                if (l.retinoid) actives.push(t('app.skincare.act.retinoid'))
                if (l.azelaic) actives.push(t('app.skincare.act.azelaic'))
                if (l.peel) actives.push(t('app.skincare.act.peel'))
                if (l.niacinamideSpf || (l as any).niacinamide_spf) actives.push(t('app.skincare.act.niacinamide_spf'))
                if (l.moisturizer) actives.push(t('app.skincare.act.moisturizer'))
                if (l.vitaminC || (l as any).vitamin_c) actives.push(t('app.skincare.act.vitamin_c'))
                return (
                  <div
                    key={l.id}
                    className="row"
                    data-item
                    style={{ gridTemplateColumns: 'minmax(0,1fr) auto' }}
                  >
                    <div>
                      <div className="t num">{shortDate(parseIsoDate(l.date), lang)}</div>
                      <div className="m">
                        {actives.join(' · ') || '—'}
                        {l.note && <><br />{l.note}</>}
                      </div>
                    </div>
                    <button
                      type="button"
                      className="ibtn"
                      onClick={() => handleDeleteLog(l.id)}
                      aria-label={t('common.delete')}
                    >
                      <Icon name="trash" />
                    </button>
                  </div>
                )
              })}
            </div>
          </section>
        </div>

        <div className="c5">
          <section className="sec o4">
            <div className="sec-h">
              <h2>{t('app.skincare.observations_title')}</h2>
              <button
                type="button"
                className="ghost"
                onClick={() => setObsOpen(true)}
              >
                <Icon name="plus" />
                <span>{t('app.skincare.observation_score')}</span>
              </button>
            </div>
            {obsOpen && (
              <div className="panel fpanel mb-s4">
                <div className="panel-h">
                  <h3>{t('app.skincare.state_score_today', { date: longDate(parseIsoDate(view.today), lang) })}</h3>
                  <button type="button" className="ibtn" onClick={() => setObsOpen(false)}>
                    <Icon name="x" />
                  </button>
                </div>
                <div className="form sk-form">
                  <label className="field">
                    <span className="flabel">{t('app.skincare.face_zone')}</span>
                    <select
                      className="input"
                      value={obsZone}
                      onChange={(e) => setObsZone(e.target.value)}
                    >
                      <option value="chin">{t('app.skincare.zone.chin')}</option>
                      <option value="cheeks">{t('app.skincare.zone.cheeks')}</option>
                      <option value="forehead">{t('app.skincare.zone.forehead')}</option>
                      <option value="nose">{t('app.skincare.zone.nose')}</option>
                      <option value="back_shoulders">{t('app.skincare.zone.back_shoulders')}</option>
                    </select>
                  </label>
                  <div className="sk-grid-2">
                    <label className="field">
                      <span className="flabel">{t('app.skincare.inflammation_scale')}</span>
                      <input
                        className="input"
                        type="number"
                        min={0}
                        max={5}
                        value={obsInf}
                        onChange={(e) => setObsInf(e.target.value)}
                      />
                    </label>
                    <label className="field">
                      <span className="flabel">{t('app.skincare.pih_scale')}</span>
                      <input
                        className="input"
                        type="number"
                        min={0}
                        max={5}
                        value={obsPih}
                        onChange={(e) => setObsPih(e.target.value)}
                      />
                    </label>
                  </div>
                  <input
                    className="input"
                    placeholder={t('app.skincare.note_ph')}
                    value={obsNote}
                    onChange={(e) => setObsNote(e.target.value)}
                  />
                  <div className="form-acts sk-form-acts">
                    <PrimaryButton className="btn grow" disabled={obsScores === null} onPress={handleSaveObservation}>
                      {t('common.save')}
                    </PrimaryButton>
                    <button
                      type="button"
                      className="ghost"
                      onClick={() => setObsOpen(false)}
                    >
                      {t('common.cancel')}
                    </button>
                  </div>
                </div>
              </div>
            )}
            <div className="rows">
              {view.observations.map((o) => {
                const inf = o.inflammation ?? o.inf ?? '—'
                const pih = o.pih ?? '—'
                const zoneLabel = o.zone ? tOr(`app.skincare.zone.${o.zone}`, o.zone) : '—'
                return (
                  <div
                    key={o.id}
                    className="row"
                    data-item
                    style={{ gridTemplateColumns: 'minmax(0,1fr) auto' }}
                  >
                    <div>
                      <div className="t num">{shortDate(parseIsoDate(o.date), lang)}</div>
                      <div className="m">
                        {t('app.skincare.obs_format', { inf, pih, zone: zoneLabel })}
                        {o.note && <><br />{o.note}</>}
                      </div>
                    </div>
                    <button
                      type="button"
                      className="ibtn"
                      onClick={() => handleDeleteObservation(o.id)}
                      aria-label={t('common.delete')}
                    >
                      <Icon name="trash" />
                    </button>
                  </div>
                )
              })}
            </div>
          </section>
        </div>
      </div>
    </>
  )
}
