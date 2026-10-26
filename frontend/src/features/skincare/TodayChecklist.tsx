import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { api, ConflictError, failText, ok, type Violation } from '@/api/client'
import { ConflictAlert } from '@/components/controls/ConflictAlert'
import { PrimaryButton } from '@/components/controls/PrimaryButton'
import { SectionHead } from '@/components/controls/Section'
import { TextButton } from '@/components/controls/Marks'
import { toast } from '@/components/controls/toast'
import { Icon } from '@/components/icons/Icon'
import { useT } from '@/i18n/useT'
import { cx } from '@/lib/cx'
import { longDate, parseIsoDate } from '@/lib/dates'
import { progressOf, SLOTS, withSlotDone, withTick, type Slot } from './plan'
import type { SkincareDayPlan, SkincareView } from './types'
import { skincareQuery } from './useSkincareView'

interface Tick {
  slot: Slot
  /** Null ticks the whole slot. */
  productId: number | null
  done: boolean
}

const SLOT_ICON = { morning: 'today', evening: 'pulse' } as const

/** The note on one slot of the day — «ретиноид сегодня пропусти». Saved as typed; an empty one
 *  removes it. The Telegram reminder already sent for the slot is redrawn by the server. */
function NoteEditor({ today, slot, initial, onDone }: { today: string; slot: Slot; initial: string; onDone: () => void }) {
  const { t } = useT()
  const queryClient = useQueryClient()
  const [text, setText] = useState(initial)

  const save = async (): Promise<boolean> => {
    try {
      const fresh = await ok(api.PUT('/api/v1/skincare/notes', { body: { date: today, slot, text: text.trim() } }))
      queryClient.setQueryData<SkincareView>(skincareQuery.queryKey, (v) => (v === undefined ? v : { ...v, plan: fresh as SkincareDayPlan }))
      void queryClient.invalidateQueries({ queryKey: ['skincare'] })
      onDone()
      return true
    } catch (err) {
      toast(failText(err, t('app.save_failed')), { icon: 'warn' })
      return false
    }
  }

  return (
    <div className="sk-note-edit">
      <textarea
        className="input"
        rows={2}
        maxLength={500}
        placeholder={t('app.skincare.slot_note_ph')}
        aria-label={t('app.skincare.note_add')}
        value={text}
        onChange={(e) => setText(e.target.value)}
      />
      <div className="form-acts">
        <PrimaryButton className="btn grow" onPress={save}>
          {t('common.save')}
        </PrimaryButton>
        <button type="button" className="ghost" onClick={onDone}>
          {t('common.cancel')}
        </button>
      </div>
    </div>
  )
}

/** Today's routine as two checklists, morning and evening. A tap is shown at once and sent in
 *  the background; the Telegram reminder for the slot is redrawn by the server. A tick a safety
 *  rule blocks is taken back and asks, like every other conflicting save. "Today" is the
 *  routine day: until the day ends (05:00 by default) it is still the evening before. */
export function TodayChecklist({ plan, today }: { plan: SkincareDayPlan; today: string }) {
  const { t, lang } = useT()
  const queryClient = useQueryClient()
  const [conflict, setConflict] = useState<{ tick: Tick; violations: Violation[] } | null>(null)
  const [editing, setEditing] = useState<Slot | null>(null)

  const setPlan = (next: (p: SkincareDayPlan) => SkincareDayPlan) =>
    queryClient.setQueryData<SkincareView>(skincareQuery.queryKey, (v) => (v === undefined ? v : { ...v, plan: next(v.plan) }))

  const send = async (tick: Tick, override = false) => {
    const before = queryClient.getQueryData<SkincareView>(skincareQuery.queryKey)
    setPlan((p) => (tick.productId === null ? withSlotDone(p, tick.slot) : withTick(p, tick.slot, tick.productId, tick.done)))
    try {
      const fresh = await ok(
        api.POST('/api/v1/skincare/checks', {
          body: { date: today, slot: tick.slot, productId: tick.productId, done: tick.done, override },
        }),
      )
      setPlan(() => fresh as SkincareDayPlan)
      setConflict(null)
      // The history, the headline and the derived log follow from the tick.
      void queryClient.invalidateQueries({ queryKey: ['skincare'] })
      void queryClient.invalidateQueries({ queryKey: ['today'] })
    } catch (err) {
      if (before !== undefined) queryClient.setQueryData(skincareQuery.queryKey, before)
      if (err instanceof ConflictError) setConflict({ tick, violations: err.violations })
      else toast(failText(err, t('app.save_failed')), { icon: 'warn' })
    }
  }

  return (
    <section className="sec">
      <SectionHead title={t('app.skincare.today_title')} meta={longDate(parseIsoDate(today), lang)} />
      <div className="sk-today">
        {SLOTS.map((slot) => {
          const items = plan[slot]
          const progress = progressOf(items)
          const open = items.filter((i) => !i.done && i.productId !== null)
          return (
            <div key={slot} className="panel sk-slot">
              <div className="panel-h">
                <h3>
                  <Icon name={SLOT_ICON[slot]} />
                  {t(`app.skincare.${slot}`)}
                </h3>
                {items.length > 0 && (
                  <span className={cx('m num', progress.done === progress.total && 'sk-all')}>
                    {t('app.skincare.progress', { done: progress.done, total: progress.total })}
                  </span>
                )}
              </div>
              {editing === slot ? (
                <NoteEditor today={today} slot={slot} initial={plan.notes?.[slot] ?? ''} onDone={() => setEditing(null)} />
              ) : (
                plan.notes?.[slot] && (
                  <p className="sk-slot-note">
                    <Icon name="info" />
                    <span>{plan.notes[slot]}</span>
                  </p>
                )
              )}
              {items.length === 0 ? (
                <p className="m sk-none">{t('app.skincare.nothing_planned')}</p>
              ) : (
                <div className="sk-checks">
                  {items.map((item) => (
                    <button
                      key={`${item.productId ?? item.name}`}
                      type="button"
                      className={cx('sk-check', item.done && 'on')}
                      aria-pressed={item.done}
                      disabled={item.productId === null}
                      onClick={() => item.productId !== null && void send({ slot, productId: item.productId, done: !item.done })}
                    >
                      <i className="mk">{item.done && <Icon name="check" />}</i>
                      <span className="nm">
                        {item.name}
                        {/* How to apply it, while it is still to be applied. */}
                        {item.how && !item.done && <span className="how">{item.how}</span>}
                      </span>
                      {!item.planned && <span className="hint">{t('app.skincare.off_plan')}</span>}
                    </button>
                  ))}
                </div>
              )}
              <div className="sk-slot-acts">
                {open.length > 1 && (
                  <TextButton icon="check" onClick={() => void send({ slot, productId: null, done: true })}>
                    {t('app.skincare.mark_all')}
                  </TextButton>
                )}
                {editing !== slot && (
                  <TextButton icon="edit" onClick={() => setEditing(slot)}>
                    {plan.notes?.[slot] ? t('app.skincare.note_edit') : t('app.skincare.note_add')}
                  </TextButton>
                )}
              </div>
            </div>
          )
        })}
      </div>
      <ConflictAlert
        violations={conflict?.violations ?? []}
        onFix={() => setConflict(null)}
        onSaveAnyway={() => conflict !== null && void send(conflict.tick, true)}
      />
    </section>
  )
}
