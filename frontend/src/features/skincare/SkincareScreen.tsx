import { useMemo, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { api } from '@/api/client'
import { ConflictAlert } from '@/components/controls/ConflictAlert'
import { Badge } from '@/components/controls/Marks'
import { PrimaryButton, type PrimaryButtonHandle } from '@/components/controls/PrimaryButton'
import { toast } from '@/components/controls/toast'
import { Icon } from '@/components/icons/Icon'
import { Headline, Mast, TopBar } from '@/components/shell/PageHead'
import { useT } from '@/i18n/useT'
import { useConflictMutation } from '@/lib/useConflictMutation'
import type { SkincareProductItem } from './types'
import { useSkincareView } from './useSkincareView'
import './skincare.css'

const DAYS7: [number, string][] = [
  [1, 'Пн'],
  [2, 'Вт'],
  [3, 'Ср'],
  [4, 'Чт'],
  [5, 'Пт'],
  [6, 'Сб'],
  [0, 'Вс'],
]

const TIME_LBL: Record<string, [string, 'cool' | 'violet' | 'good']> = {
  morning: ['Утро', 'cool'],
  evening: ['Вечер', 'violet'],
  both: ['Утро + вечер', 'good'],
}

export default function SkincareScreen() {
  const { t } = useT()
  const view = useSkincareView()
  const queryClient = useQueryClient()

  const [formOpen, setFormOpen] = useState(false)
  const [editingProduct, setEditingProduct] = useState<SkincareProductItem | null>(null)
  const [selectedDay, setSelectedDay] = useState(() => new Date().getDay())

  // Product form states
  const [name, setName] = useState('')
  const [type, setType] = useState('Ретиноид')
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
  const [obsInf, setObsInf] = useState(1)
  const [obsPih, setObsPih] = useState(1)
  const [obsZone, setObsZone] = useState('подбородок')
  const [obsNote, setObsNote] = useState('')

  const todayDow = useMemo(() => new Date().getDay(), [])
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
    setType('Ретиноид')
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
    setDefaultTime(p.defaultTime || p.time || 'evening')
    setScheduleDays(p.scheduleDays || p.days || [])
    setDescription(p.description || p.desc || '')
    setUsageInstructions(p.usageInstructions || p.use || '')
    setActive(p.active ?? p.on ?? true)
    setFormOpen(true)
  }

  const handleSaveProduct = async (): Promise<boolean> => {
    if (!name.trim()) {
      toast(t('common.required_field') || 'Name is required', { icon: 'warn' })
      return false
    }
    setIsSubmitting(true)
    try {
      if (editingProduct) {
        await api.PATCH('/api/v1/skincare/products/{product_id}', {
          params: { path: { product_id: editingProduct.id } },
          body: {
            name: name.trim(),
            type: type.trim(),
            activeIngredient: activeIngredient.trim() || null,
            description: description.trim() || null,
            usageInstructions: usageInstructions.trim() || null,
            defaultTime,
            scheduleDays,
            active,
          },
        })
        toast(t('common.saved'))
      } else {
        await api.POST('/api/v1/skincare/products', {
          body: {
            name: name.trim(),
            type: type.trim(),
            activeIngredient: activeIngredient.trim() || null,
            description: description.trim() || null,
            usageInstructions: usageInstructions.trim() || null,
            defaultTime,
            scheduleDays,
            active,
          },
        })
        toast(t('common.saved'))
      }
      setFormOpen(false)
      refresh()
      return true
    } catch (err: any) {
      toast(err.message || 'Error saving product', { icon: 'warn' })
      return false
    } finally {
      setIsSubmitting(false)
    }
  }

  const handleDeleteProduct = async (id: number) => {
    try {
      await api.DELETE('/api/v1/skincare/products/{product_id}', {
        params: { path: { product_id: id } },
      })
      toast(t('common.deleted'))
      refresh()
    } catch (err: any) {
      toast(err.message || 'Error deleting product', { icon: 'warn' })
    }
  }

  const logConflict = useConflictMutation({
    mutationFn: async ({ override }) => {
      await api.POST('/api/v1/skincare/logs', {
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
      })
      toast('Запись сохранена')
      setLogOpen(false)
      refresh()
    },
    onError: (err) => {
      toast(err.message || 'Error saving log', { icon: 'warn' })
    },
  })

  const handleDeleteLog = async (id: number) => {
    try {
      await api.DELETE('/api/v1/skincare/logs/{log_id}', {
        params: { path: { log_id: id } },
      })
      toast(t('common.deleted'))
      refresh()
    } catch (err: any) {
      toast(err.message || 'Error deleting log', { icon: 'warn' })
    }
  }

  const handleSaveObservation = async (): Promise<boolean> => {
    try {
      await api.POST('/api/v1/skincare/observations', {
        body: {
          date: view.today,
          inflammation: obsInf,
          pih: obsPih,
          zone: obsZone,
          note: obsNote.trim() || null,
        },
      })
      toast('Наблюдение сохранено')
      setObsOpen(false)
      refresh()
      return true
    } catch (err: any) {
      toast(err.message || 'Error saving observation', { icon: 'warn' })
      return false
    }
  }

  const handleDeleteObservation = async (id: number) => {
    try {
      await api.DELETE('/api/v1/skincare/observations/{obs_id}', {
        params: { path: { obs_id: id } },
      })
      toast(t('common.deleted'))
      refresh()
    } catch (err: any) {
      toast(err.message || 'Error deleting observation', { icon: 'warn' })
    }
  }

  const toggleDay = (d: number) => {
    setScheduleDays((prev) =>
      prev.includes(d) ? prev.filter((x) => x !== d) : [...prev, d]
    )
  }

  const getProdsForCell = (d: number, part: string) => {
    return activeProducts.filter((p) => {
      const pDays = p.scheduleDays || p.days || []
      const pTime = p.defaultTime || p.time
      return pDays.includes(d) && (pTime === part || pTime === 'both')
    })
  }

  return (
    <>
      <TopBar
        title={t('nav.skincare')}
        right={
          <button type="button" className="ibtn" onClick={openCreateProduct} aria-label="Добавить средство">
            <Icon name="plus" />
          </button>
        }
      />
      <Mast
        screen="skincare"
        actions={
          <button type="button" className="ghost" onClick={openCreateProduct}>
            <Icon name="plus" />
            <span>Добавить средство</span>
          </button>
        }
      />
      <Headline title={t('nav.skincare')}>
        <div className="figs inline">
          <div className="f">
            <div className="f-v">{view.activeCount}</div>
            <div className="f-l">Активные средства</div>
          </div>
          <div className="f">
            <div className="f-v">{view.totalCount}</div>
            <div className="f-l">Всего</div>
          </div>
        </div>
      </Headline>

      {/* Product Form Modal */}
      {formOpen && (
        <div className="panel fpanel mb-6" style={{ marginTop: 'var(--s6)' }}>
          <div className="panel-h">
            <h3>{editingProduct ? 'Редактировать средство' : 'Новое средство'}</h3>
            <button type="button" className="ibtn" onClick={() => setFormOpen(false)}>
              <Icon name="x" />
            </button>
          </div>
          <div className="form space-y-3">
            <label className="field">
              <span className="flabel">Название</span>
              <input
                className="input"
                placeholder="например, Дифферин (Ретиноид)"
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            </label>
            <div className="grid grid-cols-2 gap-3">
              <label className="field">
                <span className="flabel">Тип / Категория</span>
                <input
                  className="input"
                  placeholder="Ретиноид, Пилинг..."
                  value={type}
                  onChange={(e) => setType(e.target.value)}
                />
              </label>
              <label className="field">
                <span className="flabel">Действующее вещество</span>
                <input
                  className="input"
                  placeholder="Адапален 0.1%"
                  value={activeIngredient}
                  onChange={(e) => setActiveIngredient(e.target.value)}
                />
              </label>
            </div>
            <label className="field">
              <span className="flabel">Время нанесения</span>
              <select
                className="input"
                value={defaultTime}
                onChange={(e) => setDefaultTime(e.target.value)}
              >
                <option value="morning">Утро</option>
                <option value="evening">Вечер</option>
                <option value="both">Утро + вечер</option>
              </select>
            </label>
            <label className="field">
              <span className="flabel">Дни применения</span>
              <div className="opts flex gap-1 flex-wrap">
                {DAYS7.map(([d, lbl]) => (
                  <button
                    key={d}
                    type="button"
                    className={`opt ${scheduleDays.includes(d) ? 'on' : ''}`}
                    onClick={() => toggleDay(d)}
                  >
                    {lbl}
                  </button>
                ))}
              </div>
            </label>
            <label className="field">
              <span className="flabel">Описание (действие)</span>
              <textarea
                className="input"
                rows={2}
                placeholder="..."
                value={description}
                onChange={(e) => setDescription(e.target.value)}
              />
            </label>
            <label className="field">
              <span className="flabel">Инструкции по применению</span>
              <textarea
                className="input"
                rows={2}
                placeholder="..."
                value={usageInstructions}
                onChange={(e) => setUsageInstructions(e.target.value)}
              />
            </label>
            <div className="form-acts flex gap-2 pt-2">
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
          <h2>Схема ухода по дням недели</h2>
          <span className="meta">текущий день подсвечен</span>
        </div>

        {/* Desktop Table */}
        <div className="sched">
          <table>
            <thead>
              <tr>
                <th />
                {DAYS7.map(([d, n]) => (
                  <th key={d} className={d === todayDow ? 'now' : ''}>
                    {n}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              <tr>
                <td className="lbl">
                  <Icon name="today" />
                  Утро
                </td>
                {DAYS7.map(([d]) => {
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
                  Вечер
                </td>
                {DAYS7.map(([d]) => {
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
          <div className="opts flex gap-1 flex-wrap">
            {DAYS7.map(([d, n]) => (
              <button
                key={d}
                type="button"
                className={`opt ${d === selectedDay ? 'on' : ''} ${d === todayDow ? 'today' : ''}`}
                onClick={() => setSelectedDay(d)}
              >
                {n}
              </button>
            ))}
          </div>
          <div className="day-pane">
            <div className="row" style={{ gridTemplateColumns: '22px 1fr' }}>
              <span className="mi">
                <Icon name="today" />
              </span>
              <div>
                <div className="t">Утро</div>
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
                <div className="t">Вечер</div>
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
      <div className="grid mt-6">
        <div className="c7">
          <section className="sec o1">
            <div className="sec-h">
              <h2>Активные компоненты и средства</h2>
              <span className="meta">детали по применяемым продуктам</span>
            </div>
            <div className="prods">
              {view.products.map((p) => {
                const pDays = p.scheduleDays || p.days || []
                const pTime = p.defaultTime || p.time || 'evening'
                const tMeta = TIME_LBL[pTime] || ['Вечер', 'violet']
                const ingText = p.activeIngredient || p.ing
                const descText = p.description || p.desc
                const useText = p.usageInstructions || p.use
                return (
                  <div key={p.id} className="prod" data-item>
                    <div className="row prod-h" style={{ gridTemplateColumns: 'minmax(0,1fr) auto' }}>
                      <div>
                        <div className="t">{p.name}</div>
                        {ingText && <div className="m">Актив: {ingText}</div>}
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
                        <Badge tone={tMeta[1]}>{tMeta[0]}</Badge>
                        <span className="m">
                          Дни:{' '}
                          {pDays.length
                            ? DAYS7.filter(([d]) => pDays.includes(d))
                                .map(([, n]) => n)
                                .join(', ')
                            : 'Нет'}
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
              <h2>Правила безопасности</h2>
              <span className="meta">требования при работе с активами</span>
            </div>
            <div className="alerts">
              {view.rules.map((r) => (
                <div
                  key={r.id}
                  className={`alert ${r.severity === 'block' || r.sev === 'block' ? 'block' : 'warn'}`}
                >
                  <Icon name={r.hard ? 'block' : 'warn'} />
                  <div>
                    <b>{r.kind}</b>
                    <br />
                    {r.msg}
                  </div>
                </div>
              ))}
              <div className="alert info">
                <Icon name="drop" />
                <div>
                  <b>Увлажнение и барьер кожи</b>
                  <br />
                  Наносите крем через 15–20 минут после ретиноида. Если кожа «горит», шелушится
                  или стянута — пауза 2–3 дня во всех активах, оставив только увлажнение.
                </div>
              </div>
            </div>
          </section>
        </div>
      </div>

      {/* Grid: Care Logs & Observations */}
      <div className="grid mt-6">
        <div className="c7">
          <section className="sec o3">
            <div className="sec-h">
              <h2>Дневник ухода</h2>
              <button
                type="button"
                className="ghost"
                onClick={() => setLogOpen(true)}
              >
                <Icon name="plus" />
                <span>Записать уход</span>
              </button>
            </div>
            {logOpen && (
              <div className="panel fpanel mb-4">
                <div className="panel-h">
                  <h3>Что нанесено сегодня ({view.today})</h3>
                  <button type="button" className="ibtn" onClick={() => setLogOpen(false)}>
                    <Icon name="x" />
                  </button>
                </div>
                <div className="space-y-2">
                  <div className="opts flex gap-2 flex-wrap">
                    <button
                      type="button"
                      className={`opt ${retinoid ? 'on' : ''}`}
                      onClick={() => setRetinoid(!retinoid)}
                    >
                      Ретиноид
                    </button>
                    <button
                      type="button"
                      className={`opt ${azelaic ? 'on' : ''}`}
                      onClick={() => setAzelaic(!azelaic)}
                    >
                      Азелаиновая
                    </button>
                    <button
                      type="button"
                      className={`opt ${peel ? 'on' : ''}`}
                      onClick={() => setPeel(!peel)}
                    >
                      Пилинг
                    </button>
                    <button
                      type="button"
                      className={`opt ${niacinamideSpf ? 'on' : ''}`}
                      onClick={() => setNiacinamideSpf(!niacinamideSpf)}
                    >
                      Ниацинамид / SPF
                    </button>
                    <button
                      type="button"
                      className={`opt ${moisturizer ? 'on' : ''}`}
                      onClick={() => setMoisturizer(!moisturizer)}
                    >
                      Увлажнение
                    </button>
                    <button
                      type="button"
                      className={`opt ${vitaminC ? 'on' : ''}`}
                      onClick={() => setVitaminC(!vitaminC)}
                    >
                      Витамин C
                    </button>
                  </div>
                  <input
                    className="input"
                    placeholder="Заметка..."
                    value={logNote}
                    onChange={(e) => setLogNote(e.target.value)}
                  />
                  <ConflictAlert
                    violations={logConflict.violations}
                    onFix={() => logConflict.clearConflict()}
                    onSaveAnyway={() => logButtonRef.current?.press({ override: true })}
                  />
                  <div className="flex gap-2 pt-2">
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
                if (l.retinoid) actives.push('Ретиноид')
                if (l.azelaic) actives.push('Азелаиновая к-та')
                if (l.peel) actives.push('Пилинг')
                if (l.niacinamideSpf) actives.push('Ниацинамид/SPF')
                if (l.moisturizer) actives.push('Увлажняющий крем')
                if (l.vitaminC) actives.push('Витамин C')
                return (
                  <div
                    key={l.id}
                    className="row"
                    data-item
                    style={{ gridTemplateColumns: 'minmax(0,1fr) auto' }}
                  >
                    <div>
                      <div className="t num">{l.date}</div>
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
              <h2>Наблюдения по коже</h2>
              <button
                type="button"
                className="ghost"
                onClick={() => setObsOpen(true)}
              >
                <Icon name="plus" />
                <span>Оценка</span>
              </button>
            </div>
            {obsOpen && (
              <div className="panel fpanel mb-4">
                <div className="panel-h">
                  <h3>Оценка состояния ({view.today})</h3>
                  <button type="button" className="ibtn" onClick={() => setObsOpen(false)}>
                    <Icon name="x" />
                  </button>
                </div>
                <div className="space-y-3">
                  <label className="field">
                    <span className="flabel">Зона лица / тела</span>
                    <select
                      className="input"
                      value={obsZone}
                      onChange={(e) => setObsZone(e.target.value)}
                    >
                      <option value="подбородок">Подбородок</option>
                      <option value="щёки">Щёки</option>
                      <option value="лоб">Лоб</option>
                      <option value="нос">Нос</option>
                      <option value="спина">Спина / плечи</option>
                    </select>
                  </label>
                  <div className="grid grid-cols-2 gap-3">
                    <label className="field">
                      <span className="flabel">Воспаление (1–5)</span>
                      <input
                        className="input"
                        type="number"
                        min={0}
                        max={5}
                        value={obsInf}
                        onChange={(e) => setObsInf(parseInt(e.target.value) || 0)}
                      />
                    </label>
                    <label className="field">
                      <span className="flabel">Пигментация (1–5)</span>
                      <input
                        className="input"
                        type="number"
                        min={0}
                        max={5}
                        value={obsPih}
                        onChange={(e) => setObsPih(parseInt(e.target.value) || 0)}
                      />
                    </label>
                  </div>
                  <input
                    className="input"
                    placeholder="Заметка..."
                    value={obsNote}
                    onChange={(e) => setObsNote(e.target.value)}
                  />
                  <div className="flex gap-2 pt-2">
                    <PrimaryButton className="btn grow" onPress={handleSaveObservation}>
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
                const inf = o.inflammation ?? o.inf ?? 0
                const pih = o.pih ?? 0
                return (
                  <div
                    key={o.id}
                    className="row"
                    data-item
                    style={{ gridTemplateColumns: 'minmax(0,1fr) auto' }}
                  >
                    <div>
                      <div className="t num">{o.date}</div>
                      <div className="m">
                        Воспаление {inf}/5 · Пигментация {pih}/5 · Зона: {o.zone || 'лицо'}
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
