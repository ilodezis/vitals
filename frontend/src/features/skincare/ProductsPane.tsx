import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { api, failText, ok } from '@/api/client'
import { OptionGroup } from '@/components/controls/Choices'
import { ConfirmButton } from '@/components/controls/ConfirmButton'
import { Disclosure } from '@/components/controls/Disclosure'
import { PrimaryButton } from '@/components/controls/PrimaryButton'
import { Section } from '@/components/controls/Section'
import { toast } from '@/components/controls/toast'
import { Icon } from '@/components/icons/Icon'
import { useT } from '@/i18n/useT'
import { cx } from '@/lib/cx'
import { parseIsoDate } from '@/lib/dates'
import { DOW_KEYS, productDays, productTime, scheduledIn } from './plan'
import type { SkincareProductItem, SkincareView } from './types'

/** The product being edited, `'new'` for one being added, `null` while the form is shut. */
export type Editing = SkincareProductItem | 'new' | null

const TIMES = ['morning', 'evening', 'both'] as const

/** The catalog: what is applied on which day, and each product's card. */
export function ProductsPane({ view, editing, setEditing }: { view: SkincareView; editing: Editing; setEditing: (e: Editing) => void }) {
  const { t } = useT()
  return (
    <>
      {editing !== null && (
        <ProductForm
          key={editing === 'new' ? 'new' : editing.id}
          product={editing === 'new' ? null : editing}
          flags={view.flags}
          onClose={() => setEditing(null)}
        />
      )}
      {view.products.length === 0 ? (
        editing === null && <p className="m sk-none">{t('app.skincare.products_empty')}</p>
      ) : (
        <>
          <WeekMatrix view={view} />
          <ProductList view={view} onEdit={setEditing} />
        </>
      )}
    </>
  )
}

function timeLabel(t: (key: string) => string, time: string): string {
  return time === 'morning' ? t('app.skincare.morning') : time === 'both' ? t('app.skincare.both') : t('app.skincare.evening')
}

/** One row per active product, one column per weekday: a sun for the morning, a moon for the
 *  evening. The products' names are said once, not once per cell. */
function WeekMatrix({ view }: { view: SkincareView }) {
  const { t } = useT()
  const todayDow = parseIsoDate(view.today).getDay()
  const active = view.products.filter((p) => p.active || p.on)
  if (active.length === 0) return null
  return (
    <Section title={t('app.skincare.schedule_title')} meta={t('app.skincare.schedule_sub')}>
      <div className="sk-week" role="table" aria-label={t('app.skincare.schedule_title')}>
        <div className="sk-week-r sk-week-h" role="row">
          <span role="columnheader" />
          {DOW_KEYS.map(([d, k]) => (
            <span key={d} role="columnheader" className={cx(d === todayDow && 'now')}>
              {t(`proactive.day.${k}`)}
            </span>
          ))}
        </div>
        {active.map((p) => (
          <div key={p.id} className="sk-week-r" role="row">
            <span role="rowheader" className="sk-week-n">
              {p.name}
            </span>
            {DOW_KEYS.map(([d]) => {
              const morning = scheduledIn(p, d, 'morning')
              const evening = scheduledIn(p, d, 'evening')
              const words = [morning && t('app.skincare.morning'), evening && t('app.skincare.evening')].filter(Boolean).join(', ')
              return (
                <span key={d} role="cell" className={cx('sk-week-c', d === todayDow && 'now')} aria-label={words || '—'} title={words || undefined}>
                  {morning && <Icon name="today" className="am" />}
                  {evening && <Icon name="pulse" className="pm" />}
                </span>
              )
            })}
          </div>
        ))}
      </div>
    </Section>
  )
}

function ProductList({ view, onEdit }: { view: SkincareView; onEdit: (p: SkincareProductItem) => void }) {
  const { t } = useT()
  const queryClient = useQueryClient()
  const [open, setOpen] = useState<number | null>(null)

  const remove = async (id: number) => {
    try {
      await ok(api.DELETE('/api/v1/skincare/products/{product_id}', { params: { path: { product_id: id } } }))
      toast(t('common.deleted'))
      void queryClient.invalidateQueries({ queryKey: ['skincare'] })
    } catch (err) {
      toast(failText(err, t('app.delete_failed')), { icon: 'warn' })
    }
  }

  return (
    <Section title={t('app.skincare.tab.products')} meta={String(view.products.length)}>
      <div className="sk-prods">
        {view.products.map((p) => {
          const days = productDays(p)
          const dayText = days.length
            ? DOW_KEYS.filter(([d]) => days.includes(d))
                .map(([, k]) => t(`proactive.day.${k}`))
                .join(', ')
            : t('app.skincare.days_none')
          const ingredient = p.activeIngredient || p.ing
          const description = p.description || p.desc
          const usage = p.usageInstructions || p.usage_instructions || p.use
          const sub = [ingredient, timeLabel(t, productTime(p)), dayText].filter(Boolean).join(' · ')
          return (
            <Disclosure
              key={p.id}
              className={cx(!(p.active || p.on) && 'sk-off')}
              open={open === p.id}
              onToggle={() => setOpen(open === p.id ? null : p.id)}
              title={p.name}
              sub={sub}
              actions={
                <span className="acts">
                  <button type="button" className="ibtn" aria-label={t('common.edit')} onClick={() => onEdit(p)}>
                    <Icon name="edit" />
                  </button>
                  <ConfirmButton label={t('common.delete')} onConfirm={() => void remove(p.id)} />
                </span>
              }
            >
              <div className="sk-prod-b">
                {p.activeFlag && (
                  <p className="m">
                    {t('app.skincare.active_flag')}: {t(`app.skincare.act.${p.activeFlag}`)}
                  </p>
                )}
                {description && <p className="sk-prod-d">{description}</p>}
                {usage && (
                  <p className="m sk-use">
                    <Icon name="doc" />
                    <span>{usage}</span>
                  </p>
                )}
              </div>
            </Disclosure>
          )
        })}
      </div>
    </Section>
  )
}

function ProductForm({ product, flags, onClose }: { product: SkincareProductItem | null; flags: string[]; onClose: () => void }) {
  const { t } = useT()
  const queryClient = useQueryClient()
  const [name, setName] = useState(product?.name ?? '')
  const [type, setType] = useState(product?.type ?? '')
  const [ingredient, setIngredient] = useState(product?.activeIngredient || product?.ing || '')
  const [time, setTime] = useState(product === null ? 'evening' : productTime(product))
  const [days, setDays] = useState<number[]>(product === null ? [1, 3, 5] : productDays(product))
  const [flag, setFlag] = useState(product?.activeFlag ?? '')
  const [description, setDescription] = useState(product?.description || product?.desc || '')
  const [usage, setUsage] = useState(product?.usageInstructions || product?.usage_instructions || product?.use || '')
  const [active, setActive] = useState(product === null ? true : product.active || product.on)

  const toggleDay = (d: number) => setDays((prev) => (prev.includes(d) ? prev.filter((x) => x !== d) : [...prev, d].sort((a, b) => a - b)))

  const save = async (): Promise<boolean> => {
    if (!name.trim()) {
      toast(t('app.name_required'), { icon: 'warn' })
      return false
    }
    const body = {
      name: name.trim(),
      type: type.trim() || t('app.skincare.type_default'),
      activeIngredient: ingredient.trim() || null,
      defaultTime: time,
      scheduleDays: days,
      activeFlag: flag || null,
      description: description.trim() || null,
      usageInstructions: usage.trim() || null,
      active,
    }
    try {
      if (product !== null) {
        await ok(api.PATCH('/api/v1/skincare/products/{product_id}', { params: { path: { product_id: product.id } }, body }))
      } else {
        await ok(api.POST('/api/v1/skincare/products', { body }))
      }
      toast(t('common.saved'))
      void queryClient.invalidateQueries({ queryKey: ['skincare'] })
      onClose()
      return true
    } catch (err) {
      toast(failText(err, t('app.save_failed')), { icon: 'warn' })
      return false
    }
  }

  return (
    <div className="panel fpanel mb-s4">
      <div className="panel-h">
        <h3>{product !== null ? t('app.skincare.edit_product') : t('app.skincare.new_product')}</h3>
        <button type="button" className="ibtn" aria-label={t('app.close')} onClick={onClose}>
          <Icon name="x" />
        </button>
      </div>
      <div className="form sk-form">
        <label className="field">
          <span className="flabel">{t('app.skincare.product_name')}</span>
          <input className="input" placeholder={t('app.skincare.product_name_ph')} value={name} onChange={(e) => setName(e.target.value)} />
        </label>
        <div className="form-g2">
          <label className="field">
            <span className="flabel">{t('app.skincare.product_type')}</span>
            <input className="input" placeholder={t('app.skincare.product_type_ph')} value={type} onChange={(e) => setType(e.target.value)} />
          </label>
          <label className="field">
            <span className="flabel">{t('app.skincare.active_ing')}</span>
            <input className="input" placeholder={t('app.skincare.active_ing_ph')} value={ingredient} onChange={(e) => setIngredient(e.target.value)} />
          </label>
        </div>
        <div className="field">
          <span className="flabel">{t('app.skincare.apply_time')}</span>
          <OptionGroup label={t('app.skincare.apply_time')} value={time} onChange={setTime} options={TIMES.map((id) => ({ id, label: timeLabel(t, id) }))} />
        </div>
        <div className="field">
          <span className="flabel">{t('app.skincare.schedule_days')}</span>
          <div className="opts" role="group" aria-label={t('app.skincare.schedule_days')}>
            {DOW_KEYS.map(([d, k]) => (
              <button key={d} type="button" className={cx('opt', days.includes(d) && 'on')} aria-pressed={days.includes(d)} onClick={() => toggleDay(d)}>
                {t(`proactive.day.${k}`)}
              </button>
            ))}
          </div>
        </div>
        <label className="field">
          <span className="flabel">{t('app.skincare.active_flag')}</span>
          <select className="input" value={flag} onChange={(e) => setFlag(e.target.value)}>
            <option value="">{t('app.skincare.flag_none')}</option>
            {flags.map((f) => (
              <option key={f} value={f}>
                {t(`app.skincare.act.${f}`)}
              </option>
            ))}
          </select>
          <span className="fhint">{t('app.skincare.active_flag_hint')}</span>
        </label>
        <label className="field">
          <span className="flabel">{t('app.skincare.description')}</span>
          <textarea className="input" rows={2} value={description} onChange={(e) => setDescription(e.target.value)} />
        </label>
        <label className="field">
          <span className="flabel">{t('app.skincare.instructions')}</span>
          <textarea className="input" rows={2} value={usage} onChange={(e) => setUsage(e.target.value)} />
        </label>
        <button type="button" className={cx('tgl', active && 'on')} aria-pressed={active} onClick={() => setActive(!active)}>
          <i />
          {t('app.skincare.in_use')}
        </button>
        <div className="form-acts">
          <PrimaryButton className="btn grow" onPress={save}>
            {t('common.save')}
          </PrimaryButton>
          <button type="button" className="ghost" onClick={onClose}>
            {t('common.cancel')}
          </button>
        </div>
      </div>
    </div>
  )
}
