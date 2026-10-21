import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { api, ConflictError, failText, ok, type Violation } from '@/api/client'
import { ConflictAlert } from '@/components/controls/ConflictAlert'
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

/** Today's routine as two checklists, morning and evening. A tap is shown at once and sent in
 *  the background; the Telegram reminder for the slot is redrawn by the server. A tick a safety
 *  rule blocks is taken back and asks, like every other conflicting save. */
export function TodayChecklist({ plan, today }: { plan: SkincareDayPlan; today: string }) {
  const { t, lang } = useT()
  const queryClient = useQueryClient()
  const [conflict, setConflict] = useState<{ tick: Tick; violations: Violation[] } | null>(null)

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
                      <span className="nm">{item.name}</span>
                      {!item.planned && <span className="hint">{t('app.skincare.off_plan')}</span>}
                    </button>
                  ))}
                </div>
              )}
              {open.length > 1 && (
                <TextButton icon="check" className="sk-all-btn" onClick={() => void send({ slot, productId: null, done: true })}>
                  {t('app.skincare.mark_all')}
                </TextButton>
              )}
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
